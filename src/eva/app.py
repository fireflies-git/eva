from __future__ import annotations

import asyncio
import contextlib
import logging
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
from eva.config import Settings
from eva.discord import SelfbotMessageHandler, create_discord_client
from eva.discord.commands import ALLOWED_ADMIN_IDS
from eva.downloads import DownloadService, YtDLPDownloadClient
from eva.images import ImageClient, ImageDetector, ImageGenerationService
from eva.reminders import ReminderDetector, ReminderRunner, ReminderScheduler
from eva.state import (
    ChannelHistoryStore,
    RateLimiter,
    ReminderStore,
    TrackedMessageStore,
    UserMemoryStore,
    WhitelistStore,
)
from eva.state.reminders import DEFAULT_REMINDERS_PATH
from eva.state.tracked_messages import DEFAULT_TRACKED_MESSAGES_PATH
from eva.state.user_memory import DEFAULT_USER_MEMORY_PATH
from eva.state.whitelist import DEFAULT_WHITELIST_PATH
from eva.terminal import TerminalService
from eva.tools import Context7Service, PlaywrightService, ToolService

logger = logging.getLogger(__name__)


class EvaApp:
    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings
        self._ai_client = OpenAICompatibleClient(
            api_key=settings.api_key,
            base_url=settings.api_base_url,
            default_model=settings.model_name,
            timeout_seconds=settings.request_timeout_seconds,
        )
        self._terminal_service: TerminalService | None = None
        if settings.terminal_enabled:
            self._terminal_service = TerminalService(
                workdir=settings.terminal_workdir,
                shell=settings.terminal_shell,
                timeout_seconds=settings.terminal_timeout_seconds,
                max_output_chars=settings.terminal_max_output_chars,
            )
        self._download_service = DownloadService(client=YtDLPDownloadClient())

        self._tool_services: list[ToolService] = []
        if self._terminal_service is not None and settings.terminal_autonomous_enabled:
            self._tool_services.append(self._terminal_service)

        self._playwright_service: PlaywrightService | None = None
        if settings.playwright_enabled:
            self._playwright_service = PlaywrightService(
                timeout_seconds=settings.playwright_timeout_seconds,
                max_content_chars=settings.playwright_max_content_chars,
            )
            self._tool_services.append(self._playwright_service)

        self._context7_service: Context7Service | None = None
        if settings.context7_api_key:
            self._context7_service = Context7Service(
                api_key=settings.context7_api_key,
            )
            self._tool_services.append(self._context7_service)

        self._response_service = ResponseService(
            client=self._ai_client,
            model_name=settings.model_name,
            tool_services=self._tool_services,
        )

        self._image_client: ImageClient | None = None
        self._image_service: ImageGenerationService | None = None
        if settings.image_api_key:
            self._image_client = ImageClient(
                api_key=settings.image_api_key,
                base_url=settings.image_api_base_url,
                timeout_seconds=settings.request_timeout_seconds,
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
        state_dir = Path(settings.state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        self._history_store = ChannelHistoryStore(settings.max_history_messages)
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
        )
        self._rate_limiter = RateLimiter(
            max_requests=settings.rate_limit_max_requests,
            window_seconds=settings.rate_limit_window_seconds,
            exempt_user_ids=set(ALLOWED_ADMIN_IDS),
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
            account_update_planner=self._account_update_planner,
            pending_account_updates=self._pending_account_updates,
        )
        self._discord_client = create_discord_client(self._message_handler)
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
            await self._ai_client.close()
