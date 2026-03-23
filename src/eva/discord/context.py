from __future__ import annotations

import logging

import discord

from eva.ai.schemas import ChatMessage
from eva.discord.user_metadata import (
    build_user_metadata,
    format_mentions_metadata,
    format_user_metadata,
)

logger = logging.getLogger(__name__)


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
            author = format_user_metadata(build_user_metadata(msg.author))
            mentions = format_mentions_metadata(list(getattr(msg, "mentions", [])))
            message_text = f"[{timestamp}] {author}: {msg.content}"
            if mentions:
                message_text = f"{message_text} ({mentions})"
            output.append({"role": "user", "content": message_text})
    except Exception:
        logger.exception("Failed fetching channel context")
        return []

    output.reverse()
    return output


async def fetch_reply_context(message: discord.Message) -> str | None:
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
    author = format_user_metadata(build_user_metadata(ref_msg.author))
    mentions = format_mentions_metadata(list(getattr(ref_msg, "mentions", [])))
    if mentions:
        return f"{author}: {ref_msg.content} ({mentions})"
    return f"{author}: {ref_msg.content}"
