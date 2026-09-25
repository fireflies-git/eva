from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
from pathlib import Path

from eva.account_updates import PendingAccountUpdateStore
from eva.ai import (
    AccountUpdatePlanner,
    OpenAICompatibleClient,
    ReplyGenerationService,
    ResponseService,
    ResponseSplitService,
    SummarizationService,
    TOSCheckService,
)
from eva.ai.friend_request_review import FriendRequestReviewService
from eva.captcha import NopeCHAClient
from eva.config import Settings
from eva.constants import YURI_DATABASE_FILENAME
from eva.discord import SelfbotMessageHandler, create_discord_client
from eva.discord.client import CaptchaHandler
from eva.discord.commands import configured_admin_ids
from eva.discord.friend_requests import FriendRequestHandler
from eva.discord.safeguards import DiscordSafeguardNotifier
from eva.downloads import DownloadService, YtDLPDownloadClient
from eva.images import ImageClient, ImageDetector, ImageGenerationService
from eva.reminders import ReminderDetector, ReminderRunner, ReminderScheduler
from eva.runtime import validate_secure_path
from eva.state import (
    ChannelHistoryStore,
    PendingFriendRequestStore,
    RateLimiter,
    ReminderStore,
    TrackedMessageStore,
    UserMemoryStore,
    VisionImageStore,
    WhitelistStore,
)
from eva.state.pending_friend_requests import DEFAULT_PENDING_FRIEND_REQUESTS_PATH
from eva.state.reminders import DEFAULT_REMINDERS_PATH
from eva.state.tracked_messages import DEFAULT_TRACKED_MESSAGES_PATH
from eva.state.user_memory import DEFAULT_USER_MEMORY_PATH
from eva.state.whitelist import DEFAULT_WHITELIST_PATH
from eva.terminal import TerminalService
from eva.tools import Context7Service, PlaywrightService, ToolAuthorizer, ToolService
from eva.yuri import YuriImageService

logger = logging.getLogger(__name__)


class EvaApp:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings
        state_dir = validate_secure_path(Path(settings.state_dir), expect_directory=True)
        state_dir.mkdir(parents=True, exist_ok=True)
        self._ai_client = OpenAICompatibleClient(
            api_key=settings.api_key,
            base_url=settings.api_base_url,
            default_model=settings.model_name,
            timeout_seconds=settings.request_timeout_seconds,
            allow_private_outbound=settings.allow_private_outbound,
            allowed_hosts=settings.outbound_allowed_hosts or None,
            max_response_bytes=settings.max_http_response_bytes,
        )
        self._terminal_service: TerminalService | None = None
        if settings.terminal_enabled:
            self._terminal_service = TerminalService(
                workdir=settings.terminal_workdir,
                shell=settings.terminal_shell,  # nosec B604 - TerminalService never invokes a shell.
                timeout_seconds=settings.terminal_timeout_seconds,
                max_output_chars=settings.terminal_max_output_chars,
                require_sandbox=sys.platform.startswith("linux")
                or settings.terminal_command_mode == "sandbox",
            )
        self._download_service = DownloadService(
            client=YtDLPDownloadClient(
                allow_private_outbound=settings.allow_private_outbound,
                allowed_hosts=settings.outbound_allowed_hosts or None,
            ),
            allow_private_outbound=settings.allow_private_outbound,
            allowed_hosts=settings.outbound_allowed_hosts or None,
        )
        self._yuri_service = YuriImageService(
            db_path=state_dir / YURI_DATABASE_FILENAME,
        )

        self._tool_services: list[ToolService] = []
        if self._terminal_service is not None and settings.terminal_autonomous_enabled:
            self._tool_services.append(self._terminal_service)

        self._playwright_service: PlaywrightService | None = None
        if settings.playwright_enabled:
            self._playwright_service = PlaywrightService(
                timeout_seconds=settings.playwright_timeout_seconds,
                max_content_chars=settings.playwright_max_content_chars,
                allow_private_outbound=settings.allow_private_outbound,
                allowed_hosts=settings.outbound_allowed_hosts or None,
            )
            self._tool_services.append(self._playwright_service)

        self._context7_service: Context7Service | None = None
        if settings.context7_api_key:
            self._context7_service = Context7Service(
                api_key=settings.context7_api_key,
                allow_private_outbound=settings.allow_private_outbound,
                allowed_hosts=settings.outbound_allowed_hosts or None,
            )
            self._tool_services.append(self._context7_service)

        self._response_service = ResponseService(
            client=self._ai_client,
            model_name=settings.model_name,
            tool_services=self._tool_services,
            tool_authorizer=ToolAuthorizer(scope=settings.autonomous_tool_scope),
            max_tool_rounds=settings.max_autonomous_tool_rounds,
            max_tool_calls=settings.max_autonomous_tool_calls,
            max_tool_concurrency=settings.max_autonomous_tool_concurrency,
        )

        self._image_client: ImageClient | None = None
        self._image_service: ImageGenerationService | None = None
        if settings.image_api_key:
            self._image_client = ImageClient(
                api_key=settings.image_api_key,
                base_url=settings.image_api_base_url,
                timeout_seconds=settings.request_timeout_seconds,
                allow_private_outbound=settings.allow_private_outbound,
                allowed_hosts=settings.outbound_allowed_hosts or None,
                max_response_bytes=settings.max_http_response_bytes,
            )
            self._image_service = ImageGenerationService(
                client=self._image_client,
                detector=ImageDetector(
                    client=self._ai_client,
                    model_name=settings.model_name,
                ),
                model_name=settings.image_model_name,
                language=settings.image_language,
                incognito=settings.image_incognito,
            )

        self._tos_check_service = TOSCheckService(
            client=self._ai_client,
            model_name=settings.tos_model_name,
            failure_mode=settings.tos_failure_mode,
        )
        self._response_split_service = ResponseSplitService(
            client=self._ai_client,
            model_name=settings.split_model_name,
        )
        self._summarization_service = SummarizationService(
            client=self._ai_client,
            model_name=settings.model_name,
        )
        self._account_update_planner = AccountUpdatePlanner(
            client=self._ai_client,
            model_name=settings.model_name,
        )
        self._pending_account_updates = PendingAccountUpdateStore()
        self._captcha_client: NopeCHAClient | None = None
        captcha_handler: CaptchaHandler | None = None
        if settings.nopecha_enabled:
            self._captcha_client = NopeCHAClient(
                api_key=settings.nopecha_api_key,
                allow_private_outbound=settings.allow_private_outbound,
                allowed_hosts=settings.outbound_allowed_hosts or None,
            )
            captcha_handler = self._captcha_client.handle_captcha
        self._friend_request_review_service = FriendRequestReviewService(
            client=self._ai_client,
            model_name=settings.model_name,
            account_mode=settings.account_mode,
        )
        self._pending_friend_requests = PendingFriendRequestStore(
            path=state_dir / DEFAULT_PENDING_FRIEND_REQUESTS_PATH.name
        )
        admin_ids = set(settings.admin_user_ids) or set(configured_admin_ids())
        if settings.admin_user_ids:
            os.environ["ADMIN_USER_IDS"] = ",".join(str(user_id) for user_id in sorted(admin_ids))
        self._friend_request_handler = FriendRequestHandler(
            pending_store=self._pending_friend_requests,
            review_service=self._friend_request_review_service,
            admin_ids=admin_ids,
        )
        self._safeguard_notifier = DiscordSafeguardNotifier(admin_ids=admin_ids)
        self._history_store = ChannelHistoryStore(settings.max_history_messages)
        self._vision_store = VisionImageStore()
        self._tracked_messages = TrackedMessageStore(
            path=state_dir / DEFAULT_TRACKED_MESSAGES_PATH.name
        )
        self._whitelist = WhitelistStore(state_dir / DEFAULT_WHITELIST_PATH.name)
        self._user_memory = UserMemoryStore(path=state_dir / DEFAULT_USER_MEMORY_PATH.name)
        self._reminder_store = ReminderStore(path=state_dir / DEFAULT_REMINDERS_PATH.name)
        self._reminder_scheduler = ReminderScheduler(
            detector=ReminderDetector(
                client=self._ai_client,
                model_name=settings.model_name,
            ),
            store=self._reminder_store,
        )
        self._reply_generation_service = ReplyGenerationService(
            account_mode=settings.account_mode,
            response_service=self._response_service,
            image_service=self._image_service,
            reminder_scheduler=self._reminder_scheduler,
            tos_check_service=self._tos_check_service,
            terminal_enabled=settings.terminal_enabled,
            autonomous_terminal_enabled=settings.terminal_autonomous_enabled,
            playwright_enabled=settings.playwright_enabled,
            context7_enabled=settings.context7_api_key is not None,
            autonomous_tool_scope=settings.autonomous_tool_scope,
            safeguard_notifier=self._safeguard_notifier,
        )
        self._rate_limiter = RateLimiter(
            max_requests=settings.rate_limit_max_requests,
            window_seconds=settings.rate_limit_window_seconds,
            exempt_user_ids=admin_ids,
        )
        self._message_handler = SelfbotMessageHandler(
            settings=settings,
            reply_generation_service=self._reply_generation_service,
            response_split_service=self._response_split_service,
            history_store=self._history_store,
            tracked_messages=self._tracked_messages,
            whitelist=self._whitelist,
            user_memory=self._user_memory,
            reminder_store=self._reminder_store,
            rate_limiter=self._rate_limiter,
            summarization_service=self._summarization_service,
            terminal_service=self._terminal_service,
            download_service=self._download_service,
            yuri_service=self._yuri_service,
            account_update_planner=self._account_update_planner,
            pending_account_updates=self._pending_account_updates,
            friend_request_handler=self._friend_request_handler,
            vision_store=self._vision_store,
        )
        self._discord_client = create_discord_client(
            self._message_handler,
            captcha_handler=captcha_handler,
        )
        self._reminder_runner = ReminderRunner(
            store=self._reminder_store,
            client_provider=lambda: self._discord_client,
        )

    def run(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        logger.info("Starting Eva app")
        try:
            # Starts live inside the try so a mid-sequence failure still runs
            # the cleanup below (every close() is safe when never started).
            await self._ai_client.start()
            if self._captcha_client is not None:
                await self._captcha_client.start()
            if self._image_client is not None:
                await self._image_client.start()
            if self._playwright_service is not None:
                await self._playwright_service.start()
            if self._context7_service is not None:
                await self._context7_service.start()
            self._reminder_runner.start()
            await self._discord_client.start(self._settings.discord_token)
        finally:
            with contextlib.suppress(Exception):
                await self._reminder_runner.stop()
            with contextlib.suppress(Exception):
                self._whitelist.close()
            if self._context7_service is not None:
                await self._context7_service.close()
            if self._playwright_service is not None:
                await self._playwright_service.close()
            if self._image_client is not None:
                await self._image_client.close()
            if self._captcha_client is not None:
                await self._captcha_client.close()
            await self._ai_client.close()
