from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import discord

from eva.ai.client import AIClientError
from eva.ai.schemas import ChatMessage
from eva.constants import MAX_IMAGE_URLS, WARNING_MARK
from eva.images import ImageClientError, ImageResultBundle
from eva.prompts import build_search_system_prompt, build_system_prompt
from eva.search import SearchClientError, SearchResultBundle

logger = logging.getLogger(__name__)

SEARCH_FAILURE_MESSAGE = f"{WARNING_MARK} I couldn't verify that with search right now."
IMAGE_FAILURE_MESSAGE = f"{WARNING_MARK} I couldn't generate an image right now."
_IMAGE_ANSWER_PREFIX = "media generated:"


@dataclass(frozen=True, slots=True)
class ReplyOutput:
    content: str
    attachments: list[tuple[str, bytes]]


class ResponseGenerator(Protocol):
    async def generate_reply(
        self,
        *,
        system_prompt: str,
        context_messages: Sequence[ChatMessage],
        history_messages: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
        requester_context: str | None,
    ) -> str: ...


class SearchRunner(Protocol):
    async def search_if_needed(
        self,
        *,
        user_message: str,
        recent_context: Sequence[ChatMessage],
        reply_context: str | None,
    ) -> SearchResultBundle | None: ...


class ImageRunner(Protocol):
    async def generate_if_needed(
        self,
        *,
        user_message: str,
        recent_context: Sequence[ChatMessage],
        reply_context: str | None,
    ) -> ImageResultBundle | None: ...


class SearchResponseGenerator(Protocol):
    async def generate_reply(
        self,
        *,
        system_prompt: str,
        search_results: SearchResultBundle,
        recent_context: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
        requester_context: str | None,
    ) -> str: ...


class TOSChecker(Protocol):
    async def check_tos_violation(self, text: str) -> bool: ...


class ReplyGenerationService:
    def __init__(
        self,
        *,
        response_service: ResponseGenerator,
        image_service: ImageRunner | None,
        search_service: SearchRunner | None,
        search_response_service: SearchResponseGenerator | None,
        tos_check_service: TOSChecker,
    ) -> None:
        self._response_service = response_service
        self._image_service = image_service
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
        allow_image_generation: bool = True,
        requester_context: str | None = None,
    ) -> ReplyOutput:
        image_results = await self._run_image_if_needed(
            context_messages=context_messages,
            user_message=user_message,
            reply_context=reply_context,
            allow_image_generation=allow_image_generation,
        )

        if image_results is not None:
            reply = self._generate_image_reply(image_results)
        else:
            search_results = await self._run_search_if_needed(
                context_messages=context_messages,
                user_message=user_message,
                reply_context=reply_context,
            )
            if search_results is not None:
                content = await self._generate_search_reply(
                    channel=channel,
                    client=client,
                    context_messages=context_messages,
                    search_results=search_results,
                    user_message=user_message,
                    reply_context=reply_context,
                    requester_context=requester_context,
                )
                reply = ReplyOutput(content=content, attachments=[])
            else:
                system_prompt = build_system_prompt(channel, client)
                content = await self._response_service.generate_reply(
                    system_prompt=system_prompt,
                    context_messages=context_messages,
                    history_messages=history_messages,
                    user_message=user_message,
                    reply_context=reply_context,
                    requester_context=requester_context,
                )
                reply = ReplyOutput(content=content, attachments=[])

        is_violation = await self._tos_check_service.check_tos_violation(reply.content)
        if is_violation:
            logger.warning("Generated reply blocked by TOS check.")
            blocked = f"{WARNING_MARK} I can't say that. It violates my safety or TOS guidelines."
            return ReplyOutput(
                content=blocked,
                attachments=[],
            )

        return reply

    async def _run_image_if_needed(
        self,
        *,
        context_messages: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
        allow_image_generation: bool,
    ) -> ImageResultBundle | None:
        if self._image_service is None or not allow_image_generation:
            return None
        try:
            return await self._image_service.generate_if_needed(
                user_message=user_message,
                recent_context=context_messages,
                reply_context=reply_context,
            )
        except ImageClientError:
            logger.exception("Image generation request failed")
            return ImageResultBundle.error()

    def _generate_image_reply(self, results: ImageResultBundle) -> ReplyOutput:
        if results.is_error:
            return ReplyOutput(content=IMAGE_FAILURE_MESSAGE, attachments=[])

        answer = (results.answer or "").strip()
        content = _format_image_reply_text(answer)

        attachments: list[tuple[str, bytes]] = []
        for asset in results.assets[:MAX_IMAGE_URLS]:
            attachments.append((asset.filename, asset.data))

        if attachments:
            return ReplyOutput(content=content, attachments=attachments)

        if results.images:
            # If upload/download failed, fall back to URLs so Discord can still render embeds.
            urls = [
                (img.download_url or img.url).strip()
                for img in results.images[:MAX_IMAGE_URLS]
                if (img.download_url or img.url)
            ]
            if urls:
                return ReplyOutput(content="\n".join([content, *urls]), attachments=[])

        return ReplyOutput(content=IMAGE_FAILURE_MESSAGE, attachments=[])

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
        requester_context: str | None,
    ) -> str:
        if search_results.is_error:
            return SEARCH_FAILURE_MESSAGE
        if self._search_response_service is None:
            return SEARCH_FAILURE_MESSAGE

        search_prompt = build_search_system_prompt(channel, client)
        try:
            return await self._search_response_service.generate_reply(
                system_prompt=search_prompt,
                search_results=search_results,
                recent_context=context_messages,
                user_message=user_message,
                reply_context=reply_context,
                requester_context=requester_context,
            )
        except AIClientError:
            logger.exception("Search response generation failed")
            return SEARCH_FAILURE_MESSAGE


def _format_image_reply_text(answer: str) -> str:
    if not answer:
        return "Media generated."

    normalized = answer.strip()
    lowered = normalized.lower()
    if lowered.startswith(_IMAGE_ANSWER_PREFIX):
        description = normalized[len(_IMAGE_ANSWER_PREFIX) :].strip()
        if description:
            return f"> {_strip_wrapping_quotes(description)}"

    return normalized


def _strip_wrapping_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text
