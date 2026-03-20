from __future__ import annotations

import logging

import discord

from eva.ai.schemas import ChatMessage

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
            author = getattr(msg.author, "display_name", "unknown")
            output.append({"role": "user", "content": f"[{timestamp}] {author}: {msg.content}"})
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
    return f"{ref_msg.author.display_name}: {ref_msg.content}"
