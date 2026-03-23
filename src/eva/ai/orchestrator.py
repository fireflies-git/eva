from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Protocol

import discord

from eva.ai.client import AIClientError
from eva.ai.schemas import ChatMessage
from eva.constants import WARNING_MARK
from eva.prompts import build_search_system_prompt, build_system_prompt
from eva.search import SearchClientError, SearchResultBundle

logger = logging.getLogger(__name__)

SEARCH_FAILURE_MESSAGE = f"{WARNING_MARK} I couldn't verify that with search right now."


class ResponseGenerator(Protocol):
    async def generate_reply(
        self,
        *,
        system_prompt: str,
        context_messages: Sequence[ChatMessage],
        history_messages: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
    ) -> str: ...


class SearchRunner(Protocol):
    async def search_if_needed(
        self,
        *,
        user_message: str,
        recent_context: Sequence[ChatMessage],
        reply_context: str | None,
    ) -> SearchResultBundle | None: ...


class SearchResponseGenerator(Protocol):
    async def generate_reply(
        self,
        *,
        system_prompt: str,
        search_results: SearchResultBundle,
        recent_context: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
    ) -> str: ...


class TOSChecker(Protocol):
    async def check_tos_violation(self, text: str) -> bool: ...


class ReplyGenerationService:
    def __init__(
        self,
        *,
        account_mode: str,
        response_service: ResponseGenerator,
        search_service: SearchRunner | None,
        search_response_service: SearchResponseGenerator | None,
        tos_check_service: TOSChecker,
    ) -> None:
        self._account_mode = account_mode
        self._response_service = response_service
        self._search_service = search_service
        self._search_response_service = search_response_service
        self._tos_check_service = tos_check_service

    async def generate_reply(
        self,
        *,
        channel: discord.abc.Messageable,
        client: discord.Client,
        context_messages: Sequence[ChatMessage],
        history_messages: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
    ) -> str:
        search_results = await self._run_search_if_needed(
            context_messages=context_messages,
            user_message=user_message,
            reply_context=reply_context,
        )
        if search_results is not None:
            reply = await self._generate_search_reply(
                channel=channel,
                client=client,
                context_messages=context_messages,
                search_results=search_results,
                user_message=user_message,
                reply_context=reply_context,
            )
        else:
            system_prompt = build_system_prompt(channel, client, account_mode=self._account_mode)
            reply = await self._response_service.generate_reply(
                system_prompt=system_prompt,
                context_messages=context_messages,
                history_messages=history_messages,
                user_message=user_message,
                reply_context=reply_context,
            )

        is_violation = await self._tos_check_service.check_tos_violation(reply)
        if is_violation:
            logger.warning("Generated reply blocked by TOS check.")
            return f"{WARNING_MARK} I can't say that. It violates my safety or TOS guidelines."

        return reply

    async def _run_search_if_needed(
        self,
        *,
        context_messages: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
    ) -> SearchResultBundle | None:
        if self._search_service is None:
            return None
        try:
            return await self._search_service.search_if_needed(
                user_message=user_message,
                recent_context=context_messages,
                reply_context=reply_context,
            )
        except SearchClientError:
            logger.exception("Search request failed")
            return SearchResultBundle.error()

    async def _generate_search_reply(
        self,
        *,
        channel: discord.abc.Messageable,
        client: discord.Client,
        context_messages: Sequence[ChatMessage],
        search_results: SearchResultBundle,
        user_message: str,
        reply_context: str | None,
    ) -> str:
        if search_results.is_error:
            return SEARCH_FAILURE_MESSAGE
        if self._search_response_service is None:
            return SEARCH_FAILURE_MESSAGE

        search_prompt = build_search_system_prompt(
            channel,
            client,
            account_mode=self._account_mode,
        )
        try:
            return await self._search_response_service.generate_reply(
                system_prompt=search_prompt,
                search_results=search_results,
                recent_context=context_messages,
                user_message=user_message,
                reply_context=reply_context,
            )
        except AIClientError:
            logger.exception("Search response generation failed")
            return SEARCH_FAILURE_MESSAGE
