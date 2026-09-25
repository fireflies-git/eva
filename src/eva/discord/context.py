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


# Context selection is deliberately deterministic.  Keep these limits local to
# the Discord read-side because they describe how a single request is shaped,
# not user-configurable application behavior.
_REPLY_CHAIN_DEPTH = 3  # direct parent plus two ancestors
_MAX_REQUESTER_TURNS = 6
_MAX_AMBIENT_TURNS = 4
_PRIMARY_REPLY_LABEL = "[PRIMARY_REPLY_CHAIN]"
_REQUESTER_EVA_LABEL = "[REQUESTER_EVA_CONTEXT]"
_AMBIENT_LABEL = "[AMBIENT_CONTEXT]"


async def fetch_channel_context(
    channel: discord.abc.Messageable,
    *,
    limit: int,
    exclude_message_id: int | None = None,
    bot_user_id: int | None = None,
    account_mode: str = "standalone",
    is_tracked_message: Callable[[int], bool] | None = None,
    max_message_chars: int | None = None,
    max_total_chars: int | None = None,
    requester_user_id: int | None = None,
    reply_message_id: int | None = None,
) -> list[ChatMessage]:
    if not hasattr(channel, "history"):
        return []

    raw_messages: list[discord.Message] = []
    try:
        async for msg in channel.history(limit=limit, oldest_first=False):
            if not getattr(msg, "content", "") and not getattr(msg, "attachments", None):
                continue
            if exclude_message_id is not None and getattr(msg, "id", None) == exclude_message_id:
                continue
            raw_messages.append(msg)
    except Exception:
        logger.exception("Failed fetching channel context")
        return []

    reply_chain = await _fetch_reply_chain(
        channel,
        raw_messages,
        reply_message_id=reply_message_id,
        exclude_message_id=exclude_message_id,
    )
    all_messages = _deduplicate_messages([*raw_messages, *reply_chain])
    id_to_author = await _build_reply_lookup(channel, all_messages)

    ranked_context = requester_user_id is not None or reply_message_id is not None
    selected_messages: list[tuple[discord.Message, str | None]]
    if ranked_context:
        selected_messages = _select_ranked_context(
            raw_messages=raw_messages,
            reply_chain=reply_chain,
            requester_user_id=requester_user_id,
            bot_user_id=bot_user_id,
            account_mode=account_mode,
            is_tracked_message=is_tracked_message,
            exclude_message_id=exclude_message_id,
        )
    else:
        # Keep the legacy behavior for callers that do not provide request
        # metadata.  The handler always provides it, so normal replies use the
        # identity-aware selector while small utility callers remain compatible.
        selected_messages = [(msg, None) for msg in reversed(raw_messages)]

    output: list[ChatMessage] = []
    for msg, section_label in selected_messages:
        role = _context_message_role(
            msg,
            bot_user_id,
            account_mode=account_mode,
            is_tracked_message=is_tracked_message,
        )
        if (
            role == "assistant"
            and not strip_response_watermark(msg.content)
            and not getattr(msg, "attachments", None)
        ):
            continue
        serialized = _serialize_context_message(
            msg,
            id_to_author,
            strip_watermark=role == "assistant",
            max_content_chars=max_message_chars,
            section_label=section_label,
        )
        output.append({"role": role, "content": serialized})

    if max_total_chars is not None:
        return _trim_context_messages(output, max_total_chars)
    return output


async def _fetch_reply_chain(
    channel: discord.abc.Messageable,
    raw_messages: list[discord.Message],
    *,
    reply_message_id: int | None,
    exclude_message_id: int | None,
) -> list[discord.Message]:
    """Fetch the active reply parent and at most two ancestors.

    ``history`` is intentionally allowed to stay small.  Discord reply parents
    can fall outside that window, so walk the reference chain through
    ``fetch_message`` and add any available messages to the candidate set.
    Failed fetches simply leave the normal context available.
    """
    if reply_message_id is None:
        return []

    fetch_message = getattr(channel, "fetch_message", None)
    if fetch_message is None:
        return []

    by_id = {
        message_id: message
        for message in raw_messages
        if (message_id := _message_id(message)) is not None
    }
    chain: list[discord.Message] = []
    seen_ids: set[int] = set()
    next_id = reply_message_id

    for _ in range(_REPLY_CHAIN_DEPTH):
        if next_id in seen_ids or next_id == exclude_message_id:
            break
        seen_ids.add(next_id)

        message = by_id.get(next_id)
        if message is None:
            try:
                message = await fetch_message(next_id)
            except Exception:
                logger.exception("Failed to fetch reply chain message_id=%s", next_id)
                break
            if message is None:
                break

        message_id = _message_id(message)
        if message_id is None or message_id == exclude_message_id:
            break
        by_id[message_id] = message
        if not _has_context_content(message):
            break
        chain.append(message)
        next_id = _reference_message_id(message)
        if next_id is None:
            break

    return chain


def _deduplicate_messages(messages: list[discord.Message]) -> list[discord.Message]:
    seen_ids: set[int] = set()
    deduplicated: list[discord.Message] = []
    for message in messages:
        message_id = _message_id(message)
        if message_id is None:
            deduplicated.append(message)
            continue
        if message_id in seen_ids:
            continue
        seen_ids.add(message_id)
        deduplicated.append(message)
    return deduplicated


def _select_ranked_context(
    *,
    raw_messages: list[discord.Message],
    reply_chain: list[discord.Message],
    requester_user_id: int | None,
    bot_user_id: int | None,
    account_mode: str,
    is_tracked_message: Callable[[int], bool] | None,
    exclude_message_id: int | None,
) -> list[tuple[discord.Message, str | None]]:
    """Select primary, requester/Eva, and ambient context deterministically."""
    selected: dict[int, tuple[discord.Message, str]] = {}
    unkeyed_selected: list[tuple[discord.Message, str]] = []

    def add(message: discord.Message, section_label: str) -> None:
        if _message_id(message) == exclude_message_id or not _has_context_content(message):
            return
        message_id = _message_id(message)
        if message_id is None:
            if all(existing is not message for existing, _ in unkeyed_selected):
                unkeyed_selected.append((message, section_label))
            return
        existing = selected.get(message_id)
        if existing is None or existing[1] != _PRIMARY_REPLY_LABEL:
            selected[message_id] = (message, section_label)

    # The chain is the highest-priority source.  It is traversed parent first
    # so a direct parent wins over an ancestor if a duplicate is encountered;
    # final rendering below restores chronological order.
    for message in reply_chain:
        add(message, _PRIMARY_REPLY_LABEL)

    requester_turns = 0
    # ``raw_messages`` arrives newest-first from Discord.  Pick the closest
    # qualifying turns, then sort the final result oldest-first.
    for message in raw_messages:
        if _message_id(message) == exclude_message_id:
            continue
        role = _context_message_role(
            message,
            bot_user_id,
            account_mode=account_mode,
            is_tracked_message=is_tracked_message,
        )
        author_id = getattr(getattr(message, "author", None), "id", None)
        if role != "assistant" and author_id != requester_user_id:
            continue
        if _message_id(message) in selected:
            continue
        if requester_turns >= _MAX_REQUESTER_TURNS:
            break
        add(message, _REQUESTER_EVA_LABEL)
        requester_turns += 1

    ambient_turns = 0
    for message in raw_messages:
        if _message_id(message) == exclude_message_id:
            continue
        message_id = _message_id(message)
        if message_id is not None and message_id in selected:
            continue
        role = _context_message_role(
            message,
            bot_user_id,
            account_mode=account_mode,
            is_tracked_message=is_tracked_message,
        )
        author_id = getattr(getattr(message, "author", None), "id", None)
        if role == "assistant" or author_id == requester_user_id:
            continue
        if ambient_turns >= _MAX_AMBIENT_TURNS:
            break
        add(message, _AMBIENT_LABEL)
        ambient_turns += 1

    chosen: list[tuple[discord.Message, str | None]] = [
        *selected.values(),
        *unkeyed_selected,
    ]
    chosen.sort(key=lambda item: _message_sort_key(item[0]))
    return chosen


def _message_id(message: object) -> int | None:
    value = getattr(message, "id", None)
    return value if isinstance(value, int) else None


def _reference_message_id(message: object) -> int | None:
    reference = getattr(message, "reference", None)
    value = getattr(reference, "message_id", None)
    return value if isinstance(value, int) else None


def _has_context_content(message: object) -> bool:
    return bool(getattr(message, "content", "") or getattr(message, "attachments", None))


def _message_sort_key(message: object) -> tuple[float, int]:
    created_at = getattr(message, "created_at", None)
    timestamp = 0.0
    timestamp_method = getattr(created_at, "timestamp", None)
    if callable(timestamp_method):
        try:
            timestamp_value = timestamp_method()
            if isinstance(timestamp_value, (int, float)):
                timestamp = float(timestamp_value)
        except (TypeError, ValueError, OverflowError):
            timestamp = 0.0
    message_id = _message_id(message) or 0
    return timestamp, message_id


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
    max_content_chars: int | None = None,
    section_label: str | None = None,
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
    if not content:
        content = "[no text]"
    content = _truncate_context_text(content, max_content_chars)

    message_id = getattr(msg, "id", "unknown")
    parts = [f"[UNTRUSTED_DISCORD_DATA {timestamp} message_id:{message_id}] {author}"]
    if extras:
        parts.append(f" {extras}")
    parts.append(f": {content}")
    if mentions:
        parts.append(f" ({mentions})")

    serialized = "".join(parts)
    if section_label:
        return f"{section_label}\n{serialized}"
    return serialized


def _trim_context_messages(messages: list[ChatMessage], max_total_chars: int) -> list[ChatMessage]:
    """Keep prioritized serialized messages within the prompt character budget.

    Ranked replies put the active reply chain ahead of requester/Eva turns and
    ambient channel traffic. Legacy callers do not add section labels, so they
    retain the existing newest-first trimming behavior through the fallback
    bucket below.
    """
    if max_total_chars <= 0:
        return []

    has_ranked_labels = any(_has_ranked_label(message) for message in messages)
    if not has_ranked_labels:
        legacy_kept: list[ChatMessage] = []
        remaining = max_total_chars
        for message in reversed(messages):
            content = message.get("content", "")
            if not isinstance(content, str):
                continue
            if len(content) <= remaining:
                legacy_kept.append(message)
                remaining -= len(content)
                continue
            if not legacy_kept and remaining > 0:
                legacy_kept.append({
                    "role": message["role"],
                    "content": _truncate_context_text(content, remaining),
                })
            break
        return list(reversed(legacy_kept))

    buckets: tuple[tuple[str, ...], ...] = (
        (_PRIMARY_REPLY_LABEL,),
        (_REQUESTER_EVA_LABEL,),
        (_AMBIENT_LABEL,),
        ("",),
    )
    indexed_messages = list(enumerate(messages))
    kept: list[tuple[int, ChatMessage]] = []
    remaining = max_total_chars
    for bucket in buckets:
        bucket_messages = [
            (index, message)
            for index, message in indexed_messages
            if _context_bucket(message.get("content"), bucket)
        ]
        for index, message in reversed(bucket_messages):
            content = message.get("content", "")
            if not isinstance(content, str):
                continue
            separator_chars = 1 if kept else 0
            available = remaining - separator_chars
            if available <= 0:
                break
            if len(content) <= available:
                kept.append((index, message))
                remaining -= len(content) + separator_chars
                continue
            if available > 0:
                kept.append(
                    (
                        index,
                        {
                            "role": message["role"],
                            "content": _truncate_context_text(content, available),
                        },
                    )
                )
                remaining = 0
            break
        if remaining <= 0:
            break

    kept.sort(key=lambda item: item[0])
    return [message for _, message in kept]


def _has_ranked_label(message: ChatMessage) -> bool:
    content = message.get("content")
    return isinstance(content, str) and content.startswith(
        (
            _PRIMARY_REPLY_LABEL,
            _REQUESTER_EVA_LABEL,
            _AMBIENT_LABEL,
        )
    )


def _context_bucket(content: object, labels: tuple[str, ...]) -> bool:
    if not isinstance(content, str):
        return False
    if labels == ("",):
        return not any(
            content.startswith(label)
            for label in (
                _PRIMARY_REPLY_LABEL,
                _REQUESTER_EVA_LABEL,
                _AMBIENT_LABEL,
            )
        )
    return any(content.startswith(label) for label in labels)


def _truncate_context_text(content: str, max_chars: int | None) -> str:
    if max_chars is None or max_chars <= 0 or len(content) <= max_chars:
        return content
    marker = "\n[context truncated]"
    if max_chars <= len(marker):
        return content[:max_chars]
    return f"{content[: max_chars - len(marker)]}{marker}"


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


async def fetch_reply_context(
    message: discord.Message,
    *,
    max_chars: int | None = None,
) -> str | None:
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

    if not ref_msg or (not ref_msg.content and not getattr(ref_msg, "attachments", None)):
        return None
    author = format_user_metadata(build_user_metadata(ref_msg.author))
    extras = _format_reply_context_extras(ref_msg)
    mentions = format_mentions_metadata(list(getattr(ref_msg, "mentions", [])))

    content = ref_msg.content or "[no text]"
    parts = [f"[UNTRUSTED_DISCORD_DATA message_id:{ref_msg.id}] {author}: {content}"]
    if extras:
        parts.append(f" | {extras}")
    if mentions:
        parts.append(f" ({mentions})")

    return _truncate_context_text("".join(parts), max_chars)


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
