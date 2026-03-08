from __future__ import annotations

import asyncio
import logging

from eva.ai import (
    OpenAICompatibleClient,
    ReplyGenerationService,
    ResponseService,
    SearchResponseService,
)
from eva.config import Settings
from eva.discord import SelfbotMessageHandler, create_discord_client
from eva.search import SearchDetector, SearchQueryBuilder, SearchService, SerperClient
from eva.state import ChannelHistoryStore, TrackedMessageStore

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
        self._response_service = ResponseService(
            client=self._ai_client,
            model_name=settings.model_name,
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
                detector=SearchDetector(),
                query_builder=SearchQueryBuilder(
                    client=self._ai_client,
                    model_name=settings.model_name,
                ),
            )
            self._search_response_service = SearchResponseService(
                client=self._ai_client,
                model_name=settings.model_name,
            )
        self._reply_generation_service = ReplyGenerationService(
            response_service=self._response_service,
            search_service=self._search_service,
            search_response_service=self._search_response_service,
        )
        self._history_store = ChannelHistoryStore(settings.max_history_messages)
        self._tracked_messages = TrackedMessageStore()
        self._message_handler = SelfbotMessageHandler(
            settings=settings,
            reply_generation_service=self._reply_generation_service,
            history_store=self._history_store,
            tracked_messages=self._tracked_messages,
        )
        self._discord_client = create_discord_client(self._message_handler)

    def run(self) -> None:
        asyncio.run(self._run())

    async def _run(self) -> None:
        logger.info("Starting Eva app")
        await self._ai_client.start()
        if self._search_client is not None:
            await self._search_client.start()
        try:
            await self._discord_client.start(self._settings.discord_token)
        finally:
            if self._search_client is not None:
                await self._search_client.close()
            await self._ai_client.close()
