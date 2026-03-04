from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import discord

from eva.ai import AIClientError, ResponseService
from eva.ai.schemas import ChatMessage
from eva.config import Settings
from eva.constants import WARNING_MARK
from eva.discord.formatting import build_loading_text, build_response_text
from eva.prompts import build_system_prompt
from eva.state import ChannelHistoryStore, TrackedMessageStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    should_process: bool
    user_query: str = ""


def parse_trigger(
    *,
    content: str,
    trigger_prefix: str,
    is_reply_trigger: bool,
) -> TriggerDecision:
    text = content.strip()
    lowered = text.lower()

    if is_reply_trigger:
        if not text:
            return TriggerDecision(should_process=False)
        return TriggerDecision(should_process=True, user_query=text)

    prefix = trigger_prefix.lower()
    if not lowered.startswith(prefix):
        return TriggerDecision(should_process=False)

    query = text[len(trigger_prefix) :].strip()
    if not query:
        return TriggerDecision(should_process=False)
    return TriggerDecision(should_process=True, user_query=query)


async def fetch_channel_context(
    channel: discord.abc.Messageable,
    *,
    limit: int,
) -> list[ChatMessage]:
    if not hasattr(channel, "history"):
        return []

    output: list[ChatMessage] = []
    try:
        async for msg in channel.history(limit=limit, oldest_first=False):
            if not getattr(msg, "content", ""):
                continue
            timestamp = msg.created_at.strftime("%H:%M")
            author = getattr(msg.author, "display_name", "unknown")
            output.append({"role": "user", "content": f"[{timestamp}] {author}: {msg.content}"})
    except Exception:
        logger.exception("Failed fetching channel context")
        return []

    output.reverse()
    return output


class SelfbotMessageHandler:
    def __init__(
        self,
        *,
        settings: Settings,
        response_service: ResponseService,
        history_store: ChannelHistoryStore,
        tracked_messages: TrackedMessageStore,
    ) -> None:
        self._settings = settings
        self._response_service = response_service
        self._history_store = history_store
        self._tracked_messages = tracked_messages

    async def on_message(self, client: discord.Client, message: discord.Message) -> None:
        user = client.user
        if user is None or message.author.id != user.id:
            return

        original_content = message.content
        channel_id = getattr(message.channel, "id", None)
        if channel_id is None:
            return

        is_reply_trigger = False
        if message.reference and message.reference.message_id:
            is_reply_trigger = self._tracked_messages.contains(message.reference.message_id)

        decision = parse_trigger(
            content=original_content,
            trigger_prefix=self._settings.trigger_prefix,
            is_reply_trigger=is_reply_trigger,
        )

        if not decision.should_process:
            return

        reply_context = await self._get_reply_context(message)

        await self._process_response_flow(
            client=client,
            message=message,
            original_content=original_content,
            channel_id=channel_id,
            user_query=decision.user_query,
            reply_context=reply_context,
        )

    async def _process_response_flow(
        self,
        *,
        client: discord.Client,
        message: discord.Message,
        original_content: str,
        channel_id: int,
        user_query: str,
        reply_context: str | None,
    ) -> None:
        loading_text = build_loading_text(original_content)
        edit_started = time.monotonic()
        await self._safe_edit(message, loading_text)

        response_context = await fetch_channel_context(
            message.channel,
            limit=self._settings.response_context_messages,
        )
        history_messages = self._history_store.get(channel_id)
        system_prompt = build_system_prompt(message.channel, client)

        try:
            ai_reply = await self._response_service.generate_reply(
                system_prompt=system_prompt,
                context_messages=response_context,
                history_messages=history_messages,
                user_message=user_query,
                reply_context=reply_context,
            )
        except AIClientError as exc:
            logger.exception("AI response generation failed")
            ai_reply = f"{WARNING_MARK} AI error: {exc}"

        elapsed = time.monotonic() - edit_started
        if elapsed < self._settings.min_loading_seconds:
            await asyncio.sleep(self._settings.min_loading_seconds - elapsed)

        response_text = build_response_text(original_content, ai_reply)
        await self._safe_edit(message, response_text)
        self._tracked_messages.add(message.id)

        stored_user_message = user_query
        if reply_context:
            stored_user_message = f'[Replying to message: "{reply_context}"]\n\n{user_query}'
        self._history_store.append_exchange(channel_id, stored_user_message, ai_reply)

    async def _get_reply_context(self, message: discord.Message) -> str | None:
        if not (message.reference and message.reference.message_id):
            return None

        fetch_message = getattr(message.channel, "fetch_message", None)
        if fetch_message is None:
            return None

        try:
            ref_msg = await fetch_message(message.reference.message_id)
        except Exception:
            logger.exception("Failed to fetch reply context message")
            return None

        if not ref_msg or not ref_msg.content:
            return None
        return f"{ref_msg.author.display_name}: {ref_msg.content}"

    async def _safe_edit(self, message: discord.Message, content: str) -> None:
        try:
            await message.edit(content=content)
        except Exception:
            logger.exception("Failed to edit message")
