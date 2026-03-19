from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass

import discord

from eva.ai import AIClientError, ReplyGenerationService
from eva.ai.schemas import ChatMessage
from eva.config import Settings
from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.discord.formatting import build_loading_text, build_response_chunks
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

        if not is_owner and not self._whitelist.contains(message.author.id):
            return

        original_content = message.content
        channel_id = getattr(message.channel, "id", None)
        if channel_id is None:
            return

        if is_owner:
            handled = await self._try_whitelist_command(message, original_content)
            if handled:
                return

        is_reply_trigger = False
        if is_owner and message.reference and message.reference.message_id:
            is_reply_trigger = self._tracked_messages.contains(message.reference.message_id)

        decision = parse_trigger(
            content=original_content,
            trigger_prefix=self._settings.trigger_prefix,
            is_reply_trigger=is_reply_trigger,
        )

        if not decision.should_process:
            return

        reply_context = await self._get_reply_context(message)

        if is_owner:
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

        response_chunks = build_response_chunks(original_content, ai_reply)
        await self._safe_edit(message, response_chunks[0])
        self._tracked_messages.add(message.id)
        for continuation in response_chunks[1:]:
            sent_message = await self._safe_send(message.channel, continuation)
            if sent_message is not None:
                self._tracked_messages.add(sent_message.id)

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

        chunks = self._split_reply(ai_reply)
        first = await self._safe_reply(message, chunks[0])
        if first is not None:
            self._tracked_messages.add(first.id)
        for continuation in chunks[1:]:
            sent = await self._safe_send(message.channel, continuation)
            if sent is not None:
                self._tracked_messages.add(sent.id)

        stored_user_message = user_query
        if reply_context:
            stored_user_message = f'[Replying to message: "{reply_context}"]\n\n{user_query}'
        self._history_store.append_exchange(channel_id, stored_user_message, ai_reply)

    async def _try_whitelist_command(
        self,
        message: discord.Message,
        content: str,
    ) -> bool:
        lowered = content.strip().lower()
        prefix = self._settings.trigger_prefix.lower()
        if not lowered.startswith(prefix):
            return False

        # Remove the prefix and strip leading/trailing whitespace
        query = lowered[len(prefix):].strip()

        # Check if it starts with "whitelist"
        if not query.startswith("whitelist"):
            return False

        parts = query.split()
        if len(parts) < 2:
            await self._safe_edit(message, f"{X_MARK} Usage: `{self._settings.trigger_prefix.strip()} whitelist <add|remove|list>`")
            return True

        subcommand = parts[1].lower()

        if subcommand == "list":
            ids = self._whitelist.list_all()
            if not ids:
                await self._safe_edit(message, f"{CHECK_MARK} Whitelist is empty.")
            else:
                formatted = ", ".join(f"<@{uid}>" for uid in ids)
                await self._safe_edit(message, f"{CHECK_MARK} Whitelisted: {formatted}")
            return True

        if subcommand in ("add", "remove"):
            mention_match = _MENTION_RE.search(content)
            if not mention_match:
                # Fallback to checking if the 3rd argument is an ID directly
                target_id = None
                if len(parts) >= 3 and parts[2].isdigit():
                    target_id = int(parts[2])

                if not target_id:
                    await self._safe_edit(
                        message, f"{X_MARK} Mention a user or provide an ID: `{self._settings.trigger_prefix.strip()} whitelist {subcommand} @user`"
                    )
                    return True
            else:
                target_id = int(mention_match.group(1))

            if subcommand == "add":
                added = self._whitelist.add(target_id)
                if added:
                    await self._safe_edit(
                        message, f"{CHECK_MARK} <@{target_id}> added to whitelist."
                    )
                else:
                    await self._safe_edit(
                        message, f"{WARNING_MARK} <@{target_id}> is already whitelisted."
                    )
            else:
                removed = self._whitelist.remove(target_id)
                if removed:
                    await self._safe_edit(
                        message, f"{CHECK_MARK} <@{target_id}> removed from whitelist."
                    )
                else:
                    await self._safe_edit(
                        message, f"{WARNING_MARK} <@{target_id}> is not whitelisted."
                    )
            return True

        await self._safe_edit(message, f"{X_MARK} Unknown subcommand: `{subcommand}`")
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

    @staticmethod
    def _split_reply(text: str, *, limit: int = 2000) -> list[str]:
        text = text.strip() or "(empty response)"
        if len(text) <= limit:
            return [text]
        chunks: list[str] = []
        while text:
            if len(text) <= limit:
                chunks.append(text)
                break
            cut = text.rfind("\n", 0, limit)
            if cut < int(limit * 0.6):
                cut = text.rfind(" ", 0, limit)
            if cut < int(limit * 0.6):
                cut = limit
            chunks.append(text[:cut].rstrip())
            text = text[cut:].lstrip()
        return chunks
