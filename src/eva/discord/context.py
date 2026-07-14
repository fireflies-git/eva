from __future__ import annotations

import logging
from collections.abc import Mapping

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

    raw_messages: list[discord.Message] = []
    try:
        async for msg in channel.history(limit=limit, oldest_first=False):
            if not getattr(msg, "content", ""):
                continue
            if exclude_message_id is not None and getattr(msg, "id", None) == exclude_message_id:
                continue
            raw_messages.append(msg)
    except Exception:
        logger.exception("Failed fetching channel context")
        return []

    id_to_name = _build_reply_lookup(raw_messages)

    output: list[ChatMessage] = []
    for msg in reversed(raw_messages):
        serialized = _serialize_context_message(msg, id_to_name)
        output.append({"role": "user", "content": serialized})

    return output


def _build_reply_lookup(messages: list[discord.Message]) -> dict[int, str]:
    lookup: dict[int, str] = {}
    for msg in messages:
        lookup[msg.id] = build_user_metadata(msg.author).display_name
    return lookup


def _serialize_context_message(
    msg: discord.Message,
    id_to_name: Mapping[int, str],
) -> str:
    timestamp = msg.created_at.strftime("%H:%M")
    author = format_user_metadata(build_user_metadata(msg.author))
    extras = _format_message_extras(msg, id_to_name)
    mentions = format_mentions_metadata(list(getattr(msg, "mentions", [])))

    parts = [f"[{timestamp}] {author}"]
    if extras:
        parts.append(f" {extras}")
    parts.append(f": {msg.content}")
    if mentions:
        parts.append(f" ({mentions})")

    return "".join(parts)


def _format_message_extras(
    msg: discord.Message,
    id_to_name: Mapping[int, str],
) -> str | None:
    pieces: list[str] = []

    reply_info = _format_reply_indicator(msg, id_to_name)
    if reply_info:
        pieces.append(reply_info)

    if getattr(msg, "edited_at", None) is not None:
        pieces.append("edited")

    attachment_info = _format_attachments(msg)
    if attachment_info:
        pieces.append(attachment_info)

    reactions = _format_reactions(msg)
    if reactions:
        pieces.append(reactions)

    return " | ".join(pieces) if pieces else None


def _format_reply_indicator(
    msg: discord.Message,
    id_to_name: Mapping[int, str],
) -> str | None:
    ref = getattr(msg, "reference", None)
    if not ref or not getattr(ref, "message_id", None):
        return None
    target_name = id_to_name.get(ref.message_id)
    if target_name:
        return f"reply to @{target_name}"
    return "reply"


def _format_attachments(msg: discord.Message) -> str | None:
    attachments = getattr(msg, "attachments", None)
    if not attachments:
        return None
    names = [a.filename for a in attachments]
    if len(names) == 1:
        return f"attached: {names[0]}"
    return f"attached: {', '.join(names)}"


def _format_reactions(msg: discord.Message) -> str | None:
    reactions = getattr(msg, "reactions", None)
    if not reactions:
        return None
    parts: list[str] = []
    for reaction in reactions:
        if isinstance(reaction.emoji, str):
            display = str(reaction.emoji)
        else:
            display = f":{reaction.emoji.name}:"
        parts.append(f"{display} {reaction.count}")
    return ", ".join(parts)


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
    extras = _format_reply_context_extras(ref_msg)
    mentions = format_mentions_metadata(list(getattr(ref_msg, "mentions", [])))

    parts = [f"{author}: {ref_msg.content}"]
    if extras:
        parts.append(f" | {extras}")
    if mentions:
        parts.append(f" ({mentions})")

    return "".join(parts)


def _format_reply_context_extras(msg: discord.Message) -> str | None:
    pieces: list[str] = []

    if msg.edited_at is not None:
        pieces.append("edited")

    attachment_info = _format_attachments(msg)
    if attachment_info:
        pieces.append(attachment_info)

    reactions = _format_reactions(msg)
    if reactions:
        pieces.append(reactions)

    return " | ".join(pieces) if pieces else None
