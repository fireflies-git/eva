from __future__ import annotations

import asyncio
import logging
import random
import time

import discord

from eva.ai import AIClientError, ReplyGenerationService, ResponseSplitService
from eva.ai.orchestrator import ReplyOutput
from eva.config import Settings
from eva.constants import WARNING_MARK
from eva.discord.commands import handle_whitelist_command, is_admin_user
from eva.discord.context import fetch_channel_context, fetch_reply_context
from eva.discord.download_commands import handle_download_command
from eva.discord.delivery import (
    DeliveryResult,
    deliver_owner_response,
    deliver_reply_response,
    safe_edit,
    safe_reply,
    safe_reply_or_edit,
    safe_send,
)
from eva.discord.formatting import (
    build_loading_text,
    build_plain_response_chunks,
    build_response_chunk_layout,
    build_response_chunks,
    format_response_chunks,
)
from eva.discord.terminal_commands import handle_terminal_command
from eva.downloads import DownloadService
from eva.discord.triggers import TriggerDecision as TriggerDecision
from eva.discord.triggers import is_tracked_reply_trigger, parse_trigger
from eva.discord.user_metadata import build_requester_context
from eva.state import ChannelHistoryStore, TrackedMessageStore, WhitelistStore
from eva.terminal import TerminalService

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
        terminal_service: TerminalService | None,
        download_service: DownloadService | None,
        response_split_service: ResponseSplitService | None = None,
    ) -> None:
        self._settings = settings
        self._reply_generation_service = reply_generation_service
        self._history_store = history_store
        self._tracked_messages = tracked_messages
        self._whitelist = whitelist
        self._terminal_service = terminal_service
        self._download_service = download_service
        self._response_split_service = response_split_service

    async def on_message(self, client: discord.Client, message: discord.Message) -> None:
        user = client.user
        if user is None:
            return

        is_owner = message.author.id == user.id
        is_standalone = self._is_standalone_mode()

        if is_standalone:
            if is_owner:
                return
        else:
            is_admin = is_admin_user(user_id=message.author.id, is_owner=is_owner)
            if not is_admin and not self._whitelist.contains(message.author.id):
                return

        original_content = message.content
        channel_id = getattr(message.channel, "id", None)
        if channel_id is None:
            return

        if not is_standalone:
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

        terminal_response = await handle_terminal_command(
            content=original_content,
            user_id=message.author.id,
            is_owner=is_owner,
            trigger_prefix=self._settings.trigger_prefix,
            terminal_service=self._terminal_service,
        )
        if terminal_response.handled:
            await self._deliver_command_response(
                message=message,
                is_owner=is_owner,
                original_content=original_content,
                content=terminal_response.content,
            )
            return

        download_response = await handle_download_command(
            message=message,
            content=original_content,
            is_owner=is_owner,
            trigger_prefix=self._settings.trigger_prefix,
            whitelist=self._whitelist,
            download_service=self._download_service,
        )
        if download_response.handled:
            await self._deliver_command_response(
                message=message,
                is_owner=is_owner,
                original_content=original_content,
                content=download_response.content,
                attachments=download_response.attachments,
            )
            return

        is_reply_trigger = is_tracked_reply_trigger(
            message=message,
            tracked_messages=self._tracked_messages,
        )

        decision = self._decide_trigger(
            message=message,
            content=original_content,
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

        if not is_standalone and is_owner:
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
            return

        await self._process_whitelisted_user_flow(
            client=client,
            message=message,
            channel_id=channel_id,
            user_query=decision.user_query,
            reply_context=reply_context,
            allow_image_generation=not decision.is_reply_trigger,
            requester_context=requester_context,
        )

    def _decide_trigger(
        self,
        *,
        message: discord.Message,
        content: str,
        is_reply_trigger: bool,
        mention_user_id: int,
    ) -> TriggerDecision:
        if self._is_standalone_mode():
            return self._decide_standalone_trigger(
                message=message,
                content=content,
                is_reply_trigger=is_reply_trigger,
                mention_user_id=mention_user_id,
            )
        return parse_trigger(
            content=content,
            trigger_prefix=self._settings.trigger_prefix,
            is_reply_trigger=is_reply_trigger,
            mention_user_id=mention_user_id,
        )

    def _decide_standalone_trigger(
        self,
        *,
        message: discord.Message,
        content: str,
        is_reply_trigger: bool,
        mention_user_id: int,
    ) -> TriggerDecision:
        text = content.strip()
        if not text:
            return TriggerDecision(should_process=False)

        if self._is_dm_channel(message.channel):
            return TriggerDecision(should_process=True, user_query=text)

        if is_reply_trigger:
            return TriggerDecision(
                should_process=True,
                user_query=text,
                is_reply_trigger=True,
            )

        prefixed = parse_trigger(
            content=content,
            trigger_prefix=self._settings.trigger_prefix,
            is_reply_trigger=False,
            mention_user_id=None,
        )
        if prefixed.should_process:
            return prefixed

        if self._message_mentions_user(message, mention_user_id):
            query = self._strip_user_mentions(content, mention_user_id).strip()
            if query:
                return TriggerDecision(should_process=True, user_query=query)

        return TriggerDecision(should_process=False)

    @staticmethod
    def _is_dm_channel(channel: discord.abc.Messageable) -> bool:
        return getattr(channel, "guild", None) is None

    @staticmethod
    def _message_mentions_user(message: discord.Message, user_id: int) -> bool:
        raw_mentions = getattr(message, "raw_mentions", None)
        if isinstance(raw_mentions, list) and user_id in raw_mentions:
            return True
        content = getattr(message, "content", "")
        return f"<@{user_id}>" in content or f"<@!{user_id}>" in content

    @staticmethod
    def _strip_user_mentions(content: str, user_id: int) -> str:
        stripped = content.replace(f"<@{user_id}>", " ")
        stripped = stripped.replace(f"<@!{user_id}>", " ")
        return " ".join(stripped.split())

    def _is_standalone_mode(self) -> bool:
        return getattr(self._settings, "account_mode", "assistant") == "standalone"

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
        min_loading_seconds = getattr(self._settings, "min_loading_seconds", 1.0)
        if elapsed < min_loading_seconds:
            await asyncio.sleep(min_loading_seconds - elapsed)

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

        if self._is_standalone_mode():
            delivery_result = await self._deliver_standalone_reply_response(
                message=message,
                reply=ai_reply,
            )
        else:
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

    async def _deliver_standalone_reply_response(
        self,
        *,
        message: discord.Message,
        reply: ReplyOutput,
    ) -> DeliveryResult:
        chunks = await self._build_plain_response_chunks(reply.content)
        first = await safe_reply(message, chunks[0], attachments=reply.attachments)
        if first is None:
            return DeliveryResult(primary_delivered=False)

        continuation_ids, had_continuation_failures = await self._send_followup_messages(
            message.channel,
            chunks[1:],
        )
        return DeliveryResult(
            primary_delivered=True,
            tracked_message_ids=[first.id, *continuation_ids],
            had_continuation_failures=had_continuation_failures,
        )

    async def _deliver_command_response(
        self,
        *,
        message: discord.Message,
        is_owner: bool,
        original_content: str,
        content: str,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> None:
        if is_owner and not self._is_standalone_mode():
            await deliver_owner_response(
                message=message,
                original_content=original_content,
                reply_content=content,
                reply_attachments=attachments,
            )
            return

        await deliver_reply_response(
            message=message,
            reply_content=content,
            reply_attachments=attachments,
        )

    async def _build_owner_response_chunks(
        self,
        original_content: str,
        ai_reply: str,
    ) -> list[str]:
        if not self._is_standalone_mode() or self._response_split_service is None:
            return build_response_chunks(original_content, ai_reply)

        layout = build_response_chunk_layout(original_content)
        planned_chunks = await self._response_split_service.split_reply(
            reply_content=ai_reply,
            first_limit=layout.first_body_limit,
            continuation_limit=layout.continuation_body_limit,
        )
        if planned_chunks is None:
            return build_response_chunks(original_content, ai_reply)
        return format_response_chunks(original_content, planned_chunks)

    async def _build_plain_response_chunks(self, ai_reply: str) -> list[str]:
        if not self._is_standalone_mode() or self._response_split_service is None:
            return build_plain_response_chunks(ai_reply)

        planned_chunks = await self._response_split_service.split_reply(
            reply_content=ai_reply,
            first_limit=2000,
            continuation_limit=2000,
        )
        if planned_chunks is None:
            return build_plain_response_chunks(ai_reply)
        return planned_chunks

    async def _send_followup_messages(
        self,
        channel: discord.abc.Messageable,
        chunks: list[str],
    ) -> tuple[list[int], bool]:
        sent_ids: list[int] = []
        had_failures = False

        for continuation in chunks:
            if self._is_standalone_mode():
                await asyncio.sleep(self._calculate_followup_delay_seconds(continuation))
            sent = await safe_send(channel, continuation)
            if sent is None:
                had_failures = True
                continue
            self._tracked_messages.add(sent.id)
            sent_ids.append(sent.id)

        return sent_ids, had_failures

    def _calculate_followup_delay_seconds(self, content: str) -> float:
        min_delay = getattr(self._settings, "followup_delay_min_seconds", 0.75)
        max_delay = getattr(self._settings, "followup_delay_max_seconds", 1.5)
        if max_delay <= min_delay:
            return min_delay

        ratio = min(len(content) / 1200, 1.0)
        base_delay = min_delay + ((max_delay - min_delay) * ratio)
        jitter_window = min((max_delay - min_delay) * 0.1, 0.08)
        jitter = random.uniform(-jitter_window, jitter_window)
        return max(min_delay, min(max_delay, base_delay + jitter))


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
