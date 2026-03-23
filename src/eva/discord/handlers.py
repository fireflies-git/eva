from __future__ import annotations

import asyncio
import logging
import time

import discord

from eva.ai import AIClientError, ReplyGenerationService
from eva.ai.orchestrator import ReplyOutput
from eva.config import Settings
from eva.constants import WARNING_MARK
from eva.discord.commands import handle_whitelist_command, is_admin_user
from eva.discord.context import fetch_channel_context, fetch_reply_context
from eva.discord.delivery import (
    deliver_owner_response,
    deliver_reply_response,
    safe_edit,
    safe_reply_or_edit,
)
from eva.discord.formatting import build_loading_text
from eva.discord.triggers import TriggerDecision as TriggerDecision
from eva.discord.triggers import is_tracked_reply_trigger, parse_trigger
from eva.discord.user_metadata import build_requester_context
from eva.state import ChannelHistoryStore, TrackedMessageStore, WhitelistStore

logger = logging.getLogger(__name__)
interaction_logger = logging.getLogger("eva.interaction")

__all__ = ["SelfbotMessageHandler", "TriggerDecision", "parse_trigger"]


class SelfbotMessageHandler:
    def __init__(
        self,
        *,
        settings: Settings,
        reply_generation_service: ReplyGenerationService,
        history_store: ChannelHistoryStore,
        tracked_messages: TrackedMessageStore,
        whitelist: WhitelistStore,
    ) -> None:
        self._settings = settings
        self._reply_generation_service = reply_generation_service
        self._history_store = history_store
        self._tracked_messages = tracked_messages
        self._whitelist = whitelist

    async def on_message(self, client: discord.Client, message: discord.Message) -> None:
        user = client.user
        if user is None:
            return

        is_owner = message.author.id == user.id
        is_admin = is_admin_user(user_id=message.author.id, is_owner=is_owner)

        if not is_admin and not self._whitelist.contains(message.author.id):
            return

        original_content = message.content
        channel_id = getattr(message.channel, "id", None)
        if channel_id is None:
            return

        handled = await handle_whitelist_command(
            message=message,
            content=original_content,
            is_owner=is_owner,
            trigger_prefix=self._settings.trigger_prefix,
            whitelist=self._whitelist,
            reply_or_edit=safe_reply_or_edit,
        )
        if handled:
            return

        is_reply_trigger = is_tracked_reply_trigger(
            message=message,
            tracked_messages=self._tracked_messages,
        )

        decision = parse_trigger(
            content=original_content,
            trigger_prefix=self._settings.trigger_prefix,
            is_reply_trigger=is_reply_trigger,
            mention_user_id=user.id,
        )

        if not decision.should_process:
            return

        reply_context = await fetch_reply_context(message)
        requester_context = build_requester_context(message)
        interaction_logger.info(
            (
                "incoming channel_id=%s message_id=%s author_id=%s "
                "reply_trigger=%s query=%r requester=%r"
            ),
            channel_id,
            message.id,
            message.author.id,
            decision.is_reply_trigger,
            decision.user_query,
            requester_context,
        )
        interaction_logger.info(
            "AI | %s: %s",
            getattr(message.author, "display_name", "unknown"),
            original_content,
        )

        if is_owner:
            await self._process_response_flow(
                client=client,
                message=message,
                original_content=original_content,
                channel_id=channel_id,
                user_query=decision.user_query,
                reply_context=reply_context,
                allow_image_generation=not decision.is_reply_trigger,
                requester_context=requester_context,
            )
        else:
            await self._process_whitelisted_user_flow(
                client=client,
                message=message,
                channel_id=channel_id,
                user_query=decision.user_query,
                reply_context=reply_context,
                allow_image_generation=not decision.is_reply_trigger,
                requester_context=requester_context,
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
        allow_image_generation: bool,
        requester_context: str,
    ) -> None:
        response_context = await fetch_channel_context(
            message.channel,
            limit=self._settings.response_context_messages,
            exclude_message_id=message.id,
        )
        history_messages = self._history_store.get(channel_id)

        loading_text = build_loading_text(original_content)
        edit_started = time.monotonic()
        await safe_edit(message, loading_text)

        try:
            async with message.channel.typing():
                ai_reply = await self._reply_generation_service.generate_reply(
                    channel=message.channel,
                    client=client,
                    context_messages=response_context,
                    history_messages=history_messages,
                    user_message=user_query,
                    reply_context=reply_context,
                    allow_image_generation=allow_image_generation,
                    requester_context=requester_context,
                )
        except AIClientError as exc:
            logger.exception("AI response generation failed")
            ai_reply = ReplyOutput(content=f"{WARNING_MARK} AI error: {exc}", attachments=[])

        elapsed = time.monotonic() - edit_started
        if elapsed < self._settings.min_loading_seconds:
            await asyncio.sleep(self._settings.min_loading_seconds - elapsed)

        delivery_result = await deliver_owner_response(
            message=message,
            original_content=original_content,
            reply_content=ai_reply.content,
            reply_attachments=ai_reply.attachments,
        )
        for message_id in delivery_result.tracked_message_ids:
            self._tracked_messages.add(message_id)

        if delivery_result.primary_delivered:
            stored_user_message = _build_stored_user_message(
                user_query,
                reply_context,
                requester_context,
            )
            self._history_store.append_exchange(channel_id, stored_user_message, ai_reply.content)

        interaction_logger.info(
            "outgoing channel_id=%s message_id=%s delivered=%s tracked=%s response=%r",
            channel_id,
            message.id,
            delivery_result.primary_delivered,
            len(delivery_result.tracked_message_ids),
            ai_reply.content,
        )

    async def _process_whitelisted_user_flow(
        self,
        *,
        client: discord.Client,
        message: discord.Message,
        channel_id: int,
        user_query: str,
        reply_context: str | None,
        allow_image_generation: bool,
        requester_context: str,
    ) -> None:
        response_context = await fetch_channel_context(
            message.channel,
            limit=self._settings.response_context_messages,
            exclude_message_id=message.id,
        )
        history_messages = self._history_store.get(channel_id)

        try:
            async with message.channel.typing():
                ai_reply = await self._reply_generation_service.generate_reply(
                    channel=message.channel,
                    client=client,
                    context_messages=response_context,
                    history_messages=history_messages,
                    user_message=user_query,
                    reply_context=reply_context,
                    allow_image_generation=allow_image_generation,
                    requester_context=requester_context,
                )
        except AIClientError as exc:
            logger.exception("AI response generation failed")
            ai_reply = ReplyOutput(content=f"{WARNING_MARK} AI error: {exc}", attachments=[])

        delivery_result = await deliver_reply_response(
            message=message,
            reply_content=ai_reply.content,
            reply_attachments=ai_reply.attachments,
        )
        for message_id in delivery_result.tracked_message_ids:
            self._tracked_messages.add(message_id)

        if delivery_result.primary_delivered:
            stored_user_message = _build_stored_user_message(
                user_query,
                reply_context,
                requester_context,
            )
            self._history_store.append_exchange(channel_id, stored_user_message, ai_reply.content)

        interaction_logger.info(
            "outgoing channel_id=%s message_id=%s delivered=%s tracked=%s response=%r",
            channel_id,
            message.id,
            delivery_result.primary_delivered,
            len(delivery_result.tracked_message_ids),
            ai_reply.content,
        )


def _build_stored_user_message(
    user_query: str,
    reply_context: str | None,
    requester_context: str,
) -> str:
    sections = [f"[Requester metadata]\n{requester_context}"]
    if reply_context:
        sections.append(f'[Replying to message: "{reply_context}"]')
    sections.append(user_query)
    return "\n\n".join(sections)
