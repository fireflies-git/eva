from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from dataclasses import dataclass

import discord

from eva.ai import AIClientError, ReplyGenerationService, ResponseSplitService
from eva.ai.schemas import ChatMessage
from eva.config import Settings
from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.discord.formatting import (
    build_loading_text,
    build_plain_reply_chunks,
    build_response_chunk_layout,
    build_response_chunks,
    format_response_chunks,
)
from eva.state import ChannelHistoryStore, TrackedMessageStore, WhitelistStore

logger = logging.getLogger(__name__)

_MENTION_RE = re.compile(r"<@!?(\d+)>")


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    should_process: bool
    user_query: str = ""


def parse_trigger(
    *,
    content: str,
    trigger_prefix: str,
    is_reply_trigger: bool,
    mention_user_id: int | None = None,
) -> TriggerDecision:
    text = content.strip()
    lowered = text.lower()

    if is_reply_trigger:
        if not text:
            return TriggerDecision(should_process=False)
        return TriggerDecision(should_process=True, user_query=text)

    prefix = trigger_prefix.lower()
    if lowered.startswith(prefix):
        query = text[len(trigger_prefix) :].strip()
        if not query:
            return TriggerDecision(should_process=False)
        return TriggerDecision(should_process=True, user_query=query)

    if mention_user_id is None:
        return TriggerDecision(should_process=False)

    mention_prefixes = (f"<@{mention_user_id}>", f"<@!{mention_user_id}>")
    for mention_prefix in mention_prefixes:
        if text.startswith(mention_prefix):
            query = text[len(mention_prefix) :].strip()
            if not query:
                return TriggerDecision(should_process=False)
            return TriggerDecision(should_process=True, user_query=query)

    return TriggerDecision(should_process=False)


def is_tracked_reply_trigger(
    *,
    message: discord.Message,
    tracked_messages: TrackedMessageStore,
) -> bool:
    if not (message.reference and message.reference.message_id):
        return False
    return tracked_messages.contains(message.reference.message_id)


async def fetch_channel_context(
    channel: discord.abc.Messageable,
    *,
    limit: int,
    exclude_message_id: int | None = None,
) -> list[ChatMessage]:
    if not hasattr(channel, "history"):
        return []

    output: list[ChatMessage] = []
    try:
        async for msg in channel.history(limit=limit, oldest_first=False):
            if not getattr(msg, "content", ""):
                continue
            if exclude_message_id is not None and getattr(msg, "id", None) == exclude_message_id:
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
        reply_generation_service: ReplyGenerationService,
        response_split_service: ResponseSplitService,
        history_store: ChannelHistoryStore,
        tracked_messages: TrackedMessageStore,
        whitelist: WhitelistStore,
    ) -> None:
        self._settings = settings
        self._reply_generation_service = reply_generation_service
        self._response_split_service = response_split_service
        self._history_store = history_store
        self._tracked_messages = tracked_messages
        self._whitelist = whitelist

    async def on_message(self, client: discord.Client, message: discord.Message) -> None:
        user = client.user
        if user is None:
            return

        is_owner = message.author.id == user.id
        is_standalone = self._settings.account_mode == "standalone"

        if is_standalone:
            if is_owner:
                return
        elif not is_owner and not self._whitelist.contains(message.author.id):
            return

        original_content = message.content
        channel_id = getattr(message.channel, "id", None)
        if channel_id is None:
            return

        if not is_standalone and (is_owner or self._whitelist.contains(message.author.id)):
            handled = await self._try_whitelist_command(
                message, original_content, is_owner=is_owner
            )
            if handled:
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

        reply_context = await self._get_reply_context(message)

        if not is_standalone and is_owner:
            await self._process_response_flow(
                client=client,
                message=message,
                original_content=original_content,
                channel_id=channel_id,
                user_query=decision.user_query,
                reply_context=reply_context,
            )
        else:
            await self._process_whitelisted_user_flow(
                client=client,
                message=message,
                channel_id=channel_id,
                user_query=decision.user_query,
                reply_context=reply_context,
            )

    def _decide_trigger(
        self,
        *,
        message: discord.Message,
        content: str,
        is_reply_trigger: bool,
        mention_user_id: int,
    ) -> TriggerDecision:
        if self._settings.account_mode == "standalone":
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
            return TriggerDecision(should_process=True, user_query=text)

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
        response_context = await fetch_channel_context(
            message.channel,
            limit=self._settings.response_context_messages,
            exclude_message_id=message.id,
        )
        history_messages = self._history_store.get(channel_id)

        loading_text = build_loading_text(original_content)
        edit_started = time.monotonic()
        await self._safe_edit(message, loading_text)

        try:
            async with message.channel.typing():
                ai_reply = await self._reply_generation_service.generate_reply(
                    channel=message.channel,
                    client=client,
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

        response_chunks = await self._build_owner_response_chunks(original_content, ai_reply)
        await self._safe_edit(message, response_chunks[0])
        self._tracked_messages.add(message.id)
        await self._send_followup_messages(message.channel, response_chunks[1:])

        stored_user_message = user_query
        if reply_context:
            stored_user_message = f'[Replying to message: "{reply_context}"]\n\n{user_query}'
        self._history_store.append_exchange(channel_id, stored_user_message, ai_reply)

    async def _process_whitelisted_user_flow(
        self,
        *,
        client: discord.Client,
        message: discord.Message,
        channel_id: int,
        user_query: str,
        reply_context: str | None,
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
                )
        except AIClientError as exc:
            logger.exception("AI response generation failed")
            ai_reply = f"{WARNING_MARK} AI error: {exc}"

        chunks = await self._build_plain_response_chunks(ai_reply)
        first = await self._safe_reply(message, chunks[0])
        if first is not None:
            self._tracked_messages.add(first.id)
        await self._send_followup_messages(message.channel, chunks[1:])

        stored_user_message = user_query
        if reply_context:
            stored_user_message = f'[Replying to message: "{reply_context}"]\n\n{user_query}'
        self._history_store.append_exchange(channel_id, stored_user_message, ai_reply)

    async def _try_whitelist_command(
        self,
        message: discord.Message,
        content: str,
        is_owner: bool = False,
    ) -> bool:
        lowered = content.strip().lower()
        prefix = self._settings.trigger_prefix.lower()
        if not lowered.startswith(prefix):
            return False

        # Remove the prefix and strip leading/trailing whitespace
        query = lowered[len(prefix) :].strip()

        # Check if it starts with "whitelist"
        if not query.startswith("whitelist"):
            return False

        parts = query.split()
        if len(parts) < 2:
            usage = f"{self._settings.trigger_prefix.strip()} whitelist <add|remove|list>"
            await self._safe_reply_or_edit(
                message,
                is_owner,
                f"{X_MARK} Usage: `{usage}`",
            )
            return True

        subcommand = parts[1].lower()

        ALLOWED_ADMIN_IDS = {213766338005434370, 218675193592283137}
        is_admin = is_owner or message.author.id in ALLOWED_ADMIN_IDS

        if subcommand == "list":
            ids = self._whitelist.list_all()
            if not ids:
                await self._safe_reply_or_edit(
                    message, is_owner, f"{CHECK_MARK} Whitelist is empty."
                )
            else:
                formatted = ", ".join(f"<@{uid}>" for uid in ids)
                await self._safe_reply_or_edit(
                    message, is_owner, f"{CHECK_MARK} Whitelisted: {formatted}"
                )
            return True

        if subcommand in ("add", "remove"):
            if not is_admin:
                await self._safe_reply_or_edit(
                    message,
                    is_owner,
                    f"{X_MARK} You don't have permission to modify the whitelist.",
                )
                return True

            mention_match = _MENTION_RE.search(content)
            if not mention_match:
                # Fallback to checking if the 3rd argument is an ID directly
                target_id = None
                if len(parts) >= 3 and parts[2].isdigit():
                    target_id = int(parts[2])

                if not target_id:
                    usage = f"{self._settings.trigger_prefix.strip()} whitelist {subcommand} @user"
                    await self._safe_reply_or_edit(
                        message,
                        is_owner,
                        f"{X_MARK} Mention a user or provide an ID: `{usage}`",
                    )
                    return True
            else:
                target_id = int(mention_match.group(1))

            if subcommand == "add":
                added = self._whitelist.add(target_id)
                if added:
                    await self._safe_reply_or_edit(
                        message, is_owner, f"{CHECK_MARK} <@{target_id}> added to whitelist."
                    )
                else:
                    await self._safe_reply_or_edit(
                        message, is_owner, f"{WARNING_MARK} <@{target_id}> is already whitelisted."
                    )
            else:
                removed = self._whitelist.remove(target_id)
                if removed:
                    await self._safe_reply_or_edit(
                        message, is_owner, f"{CHECK_MARK} <@{target_id}> removed from whitelist."
                    )
                else:
                    await self._safe_reply_or_edit(
                        message, is_owner, f"{WARNING_MARK} <@{target_id}> is not whitelisted."
                    )
            return True

        await self._safe_reply_or_edit(
            message, is_owner, f"{X_MARK} Unknown subcommand: `{subcommand}`"
        )
        return True

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

    async def _safe_reply_or_edit(
        self, message: discord.Message, is_owner: bool, content: str
    ) -> None:
        if is_owner:
            await self._safe_edit(message, content)
        else:
            await self._safe_reply(message, content)

    async def _safe_edit(self, message: discord.Message, content: str) -> None:
        try:
            await message.edit(content=content, suppress=True)
        except Exception:
            logger.exception("Failed to edit message")

    async def _safe_send(
        self,
        channel: discord.abc.Messageable,
        content: str,
    ) -> discord.Message | None:
        send = getattr(channel, "send", None)
        if send is None:
            return None
        try:
            return await send(content=content, suppress_embeds=True)
        except Exception:
            logger.exception("Failed to send continuation message")
            return None

    async def _safe_reply(
        self,
        message: discord.Message,
        content: str,
    ) -> discord.Message | None:
        try:
            return await message.reply(content=content, suppress_embeds=True)
        except Exception:
            logger.exception("Failed to reply to message")
            return None

    async def _build_owner_response_chunks(
        self,
        original_content: str,
        ai_reply: str,
    ) -> list[str]:
        if self._settings.account_mode != "standalone":
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
        if self._settings.account_mode != "standalone":
            return build_plain_reply_chunks(ai_reply)

        planned_chunks = await self._response_split_service.split_reply(
            reply_content=ai_reply,
            first_limit=2000,
            continuation_limit=2000,
        )
        if planned_chunks is None:
            return build_plain_reply_chunks(ai_reply)
        return planned_chunks

    async def _send_followup_messages(
        self,
        channel: discord.abc.Messageable,
        chunks: list[str],
    ) -> None:
        for continuation in chunks:
            if self._settings.account_mode == "standalone":
                await asyncio.sleep(self._calculate_followup_delay_seconds(continuation))
            sent = await self._safe_send(channel, continuation)
            if sent is not None:
                self._tracked_messages.add(sent.id)

    def _calculate_followup_delay_seconds(self, content: str) -> float:
        min_delay = self._settings.followup_delay_min_seconds
        max_delay = self._settings.followup_delay_max_seconds
        if max_delay <= min_delay:
            return min_delay

        ratio = min(len(content) / 1200, 1.0)
        base_delay = min_delay + ((max_delay - min_delay) * ratio)
        jitter_window = min((max_delay - min_delay) * 0.1, 0.08)
        jitter = random.uniform(-jitter_window, jitter_window)
        return max(min_delay, min(max_delay, base_delay + jitter))
