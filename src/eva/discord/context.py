from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping

import discord

from eva.ai.sanitize import strip_response_watermark
from eva.ai.schemas import ChatMessage
from eva.discord.user_metadata import (
    UserMetadata,
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
    bot_user_id: int | None = None,
    account_mode: str = "standalone",
    is_tracked_message: Callable[[int], bool] | None = None,
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

    id_to_author = await _build_reply_lookup(channel, raw_messages)

    output: list[ChatMessage] = []
    for msg in reversed(raw_messages):
        role = _context_message_role(
            msg,
            bot_user_id,
            account_mode=account_mode,
            is_tracked_message=is_tracked_message,
        )
        if role == "assistant" and not strip_response_watermark(msg.content):
            continue
        serialized = _serialize_context_message(
            msg,
            id_to_author,
            strip_watermark=role == "assistant",
        )
        output.append({"role": role, "content": serialized})

    return output


async def _build_reply_lookup(
    channel: discord.abc.Messageable,
    messages: list[discord.Message],
) -> dict[int, UserMetadata]:
    lookup: dict[int, UserMetadata] = {}
    for msg in messages:
        lookup[msg.id] = build_user_metadata(msg.author)

    missing_ids = {
        ref.message_id
        for msg in messages
        if (ref := getattr(msg, "reference", None)) is not None
        and getattr(ref, "message_id", None) is not None
        and ref.message_id not in lookup
    }
    fetch_message = getattr(channel, "fetch_message", None)
    if fetch_message is None or not missing_ids:
        return lookup

    results = await asyncio.gather(
        *(fetch_message(message_id) for message_id in missing_ids),
        return_exceptions=True,
    )
    for message_id, result in zip(missing_ids, results, strict=True):
        if isinstance(result, BaseException) or result is None:
            continue
        author = getattr(result, "author", None)
        if author is not None:
            lookup[message_id] = build_user_metadata(author)
    return lookup


def _serialize_context_message(
    msg: discord.Message,
    id_to_author: Mapping[int, UserMetadata],
    *,
    strip_watermark: bool = False,
) -> str:
    timestamp = msg.created_at.strftime("%H:%M")
    author = format_user_metadata(build_user_metadata(msg.author))
    extras = _format_message_extras(msg, id_to_author)
    mentions = format_mentions_metadata(list(getattr(msg, "mentions", [])))

    content = msg.content
    if strip_watermark:
        # Keep the visible watermark out of the model prompt so it doesn't
        # learn to regurgitate it.
        content = strip_response_watermark(content)

    message_id = getattr(msg, "id", "unknown")
    parts = [f"[{timestamp} message_id:{message_id}] {author}"]
    if extras:
        parts.append(f" {extras}")
    parts.append(f": {content}")
    if mentions:
        parts.append(f" ({mentions})")

    return "".join(parts)


def _format_message_extras(
    msg: discord.Message,
    id_to_author: Mapping[int, UserMetadata],
) -> str | None:
    pieces: list[str] = []

    reply_info = _format_reply_indicator(msg, id_to_author)
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
    id_to_author: Mapping[int, UserMetadata],
) -> str | None:
    ref = getattr(msg, "reference", None)
    if not ref or not getattr(ref, "message_id", None):
        return None
    target_author = id_to_author.get(ref.message_id)
    if target_author is not None:
        return (
            f"reply to {format_user_metadata(target_author)} "
            f"[message_id:{ref.message_id}]"
        )
    return f"reply to message_id:{ref.message_id}"


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

    parts = [f"[message_id:{ref_msg.id}] {author}: {ref_msg.content}"]
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


def _context_message_role(
    msg: discord.Message,
    bot_user_id: int | None,
    *,
    account_mode: str,
    is_tracked_message: Callable[[int], bool] | None,
) -> str:
    message_id = getattr(msg, "id", None)
    if (
        account_mode == "assistant"
        and isinstance(message_id, int)
        and is_tracked_message is not None
        and is_tracked_message(message_id)
    ):
        return "assistant"
    if (
        account_mode != "assistant"
        and bot_user_id is not None
        and getattr(msg.author, "id", None) == bot_user_id
    ):
        return "assistant"
    return "user"
