from __future__ import annotations

import asyncio
import contextlib
import logging

from eva.ai import (
    OpenAICompatibleClient,
    ReplyGenerationService,
    ResponseService,
    ResponseSplitService,
    SearchResponseService,
    SummarizationService,
    TOSCheckService,
)
from eva.config import Settings
from eva.discord import SelfbotMessageHandler, create_discord_client
from eva.discord.commands import ALLOWED_ADMIN_IDS
from eva.downloads import DownloadService, YtDLPDownloadClient
from eva.images import ImageClient, ImageDetector, ImageGenerationService
from eva.reminders import ReminderRunner
from eva.search import SearchDetector, SearchQueryBuilder, SearchService, SerperClient
from eva.state import (
    ChannelHistoryStore,
    ChannelResponseStore,
    RateLimiter,
    ReminderStore,
    TrackedMessageStore,
    UserMemoryStore,
    WhitelistStore,
)
from eva.terminal import TerminalService

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
        self._response_service = ResponseService(
            client=self._ai_client,
            model_name=settings.model_name,
            terminal_service=self._terminal_service,
            autonomous_terminal_access=settings.terminal_autonomous_enabled,
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

        self._search_client: SerperClient | None = None
        self._search_service: SearchService | None = None
        self._search_response_service: SearchResponseService | None = None
        if settings.serper_api_key:
            self._search_client = SerperClient(
                api_key=settings.serper_api_key,
                timeout_seconds=settings.request_timeout_seconds,
            )
            self._search_service = SearchService(
                client=self._search_client,
                detector=SearchDetector(
                    client=self._ai_client,
                    model_name=settings.model_name,
                ),
                query_builder=SearchQueryBuilder(
                    client=self._ai_client,
                    model_name=settings.model_name,
                ),
            )
            self._search_response_service = SearchResponseService(
                client=self._ai_client,
                model_name=settings.model_name,
                terminal_service=self._terminal_service,
                autonomous_terminal_access=settings.terminal_autonomous_enabled,
            )
        self._tos_check_service = TOSCheckService(
            client=self._ai_client,
        )
        self._response_split_service = ResponseSplitService(
            client=self._ai_client,
            model_name=settings.split_model_name,
        )
        self._summarization_service = SummarizationService(
            client=self._ai_client,
            model_name=settings.model_name,
        )
        self._reply_generation_service = ReplyGenerationService(
            account_mode=settings.account_mode,
            response_service=self._response_service,
            image_service=self._image_service,
            search_service=self._search_service,
            search_response_service=self._search_response_service,
            tos_check_service=self._tos_check_service,
            terminal_enabled=settings.terminal_enabled,
            autonomous_terminal_enabled=settings.terminal_autonomous_enabled,
        )
        self._history_store = ChannelHistoryStore(settings.max_history_messages)
        self._response_store = ChannelResponseStore()
        self._tracked_messages = TrackedMessageStore()
        self._whitelist = WhitelistStore()
        self._user_memory = UserMemoryStore()
        self._reminder_store = ReminderStore()
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
            response_store=self._response_store,
            tracked_messages=self._tracked_messages,
            whitelist=self._whitelist,
            user_memory=self._user_memory,
            reminder_store=self._reminder_store,
            rate_limiter=self._rate_limiter,
            summarization_service=self._summarization_service,
            terminal_service=self._terminal_service,
            download_service=self._download_service,
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
        await self._ai_client.start()
        if self._image_client is not None:
            await self._image_client.start()
        if self._search_client is not None:
            await self._search_client.start()
        self._reminder_runner.start()
        try:
            await self._discord_client.start(self._settings.discord_token)
        finally:
            with contextlib.suppress(Exception):
                await self._reminder_runner.stop()
            if self._search_client is not None:
                await self._search_client.close()
            if self._image_client is not None:
                await self._image_client.close()
            await self._ai_client.close()
