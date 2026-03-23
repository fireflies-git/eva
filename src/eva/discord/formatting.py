from __future__ import annotations

import random
import re
from dataclasses import dataclass

from eva.constants import DISCORD_MESSAGE_LIMIT, LOADING_MESSAGES

EMPTY_RESPONSE = "(empty response)"
QUOTE_PREFIX = "-# > "
QUOTE_SEPARATOR = "\n "
CONTINUATION_PREFIX = "-# (cont.)\n "
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s)")


@dataclass(frozen=True, slots=True)
class ResponseChunkLayout:
    safe_original: str
    first_prefix: str
    continuation_prefix: str
    first_body_limit: int
    continuation_body_limit: int


def build_loading_text(original_content: str) -> str:
    loading = random.choice(LOADING_MESSAGES)
    return f"-# > {original_content}\n {loading}"


def _take_chunk(text: str, max_len: int) -> tuple[str, str]:
    if len(text) <= max_len:
        return text, ""

    cut = max_len
    newline_cut = text.rfind("\n", 0, cut)
    space_cut = text.rfind(" ", 0, cut)
    split_at = max(newline_cut, space_cut)
    if split_at >= int(max_len * 0.6):
        cut = split_at

    part = text[:cut].rstrip()
    if not part:
        part = text[:max_len]
        cut = max_len
    remainder = text[cut:].lstrip()
    return part, remainder


def _is_list_item(line: str) -> bool:
    return bool(_LIST_ITEM_RE.match(line))


def _split_into_sections(text: str) -> list[str]:
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return [EMPTY_RESPONSE]

    sections: list[str] = []
    current: list[str] = []
    in_code_block = False

    def flush() -> None:
        if not current:
            return
        chunk = "\n".join(current).strip()
        if chunk:
            sections.append(chunk)
        current.clear()

    for line in normalized.split("\n"):
        stripped = line.strip()
        is_fence = stripped.startswith("```")
        is_list_item = _is_list_item(stripped)
        current_is_list = bool(current) and all(
            _is_list_item(item.strip()) for item in current if item.strip()
        )

        if in_code_block:
            current.append(line)
            if is_fence:
                in_code_block = False
                flush()
            continue

        if is_fence:
            flush()
            current.append(line)
            in_code_block = True
            continue

        if not stripped:
            flush()
            continue

        if current and current_is_list and not is_list_item:
            flush()
        elif current and is_list_item and not current_is_list:
            flush()

        current.append(line)

    flush()
    return sections or [EMPTY_RESPONSE]


def split_reply_for_limits(
    reply_content: str,
    *,
    first_limit: int,
    continuation_limit: int,
) -> list[str]:
    sections = _split_into_sections(reply_content)
    chunks: list[str] = []
    current = ""
    current_limit = max(first_limit, 1)

    def flush_current() -> None:
        nonlocal current, current_limit
        if not current:
            return
        chunks.append(current)
        current = ""
        current_limit = max(continuation_limit, 1)

    for section in sections:
        pending = section.strip() or EMPTY_RESPONSE

        if not current:
            while len(pending) > current_limit:
                piece, pending = _take_chunk(pending, current_limit)
                chunks.append(piece)
                current_limit = max(continuation_limit, 1)
            current = pending
            continue

        combined = f"{current}\n\n{pending}"
        if len(combined) <= current_limit:
            current = combined
            continue

        flush_current()
        while len(pending) > current_limit:
            piece, pending = _take_chunk(pending, current_limit)
            chunks.append(piece)
            current_limit = max(continuation_limit, 1)
        current = pending

    flush_current()
    return chunks or [EMPTY_RESPONSE]


def split_message_content(
    text: str,
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    return split_reply_for_limits(
        text,
        first_limit=message_limit,
        continuation_limit=message_limit,
    )


def build_response_chunk_layout(
    original_content: str,
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> ResponseChunkLayout:
    safe_original = original_content
    max_original_len = message_limit - len(QUOTE_PREFIX) - len(QUOTE_SEPARATOR) - 120
    if max_original_len < 0:
        max_original_len = 0
    if len(safe_original) > max_original_len:
        if max_original_len > 3:
            safe_original = safe_original[: max_original_len - 3] + "..."
        else:
            safe_original = ""

    first_prefix = f"{QUOTE_PREFIX}{safe_original}{QUOTE_SEPARATOR}"
    first_room = message_limit - len(first_prefix)
    if first_room <= 0:
        first_room = 1

    continuation_room = message_limit - len(CONTINUATION_PREFIX)
    if continuation_room <= 0:
        continuation_room = 1

    return ResponseChunkLayout(
        safe_original=safe_original,
        first_prefix=first_prefix,
        continuation_prefix=CONTINUATION_PREFIX,
        first_body_limit=first_room,
        continuation_body_limit=continuation_room,
    )


def format_response_chunks(
    original_content: str,
    chunk_bodies: list[str],
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    layout = build_response_chunk_layout(original_content, message_limit=message_limit)
    bodies = [body.strip() for body in chunk_bodies if body.strip()] or [EMPTY_RESPONSE]

    chunks = [f"{layout.first_prefix}{bodies[0]}"]
    for body in bodies[1:]:
        chunks.append(f"{layout.continuation_prefix}{body}")
    return chunks


def build_plain_response_chunks(
    reply_content: str,
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    return split_message_content(reply_content, message_limit=message_limit)


def build_plain_reply_chunks(
    reply_content: str,
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    return build_plain_response_chunks(reply_content, message_limit=message_limit)


def build_response_chunks(
    original_content: str,
    reply_content: str,
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    layout = build_response_chunk_layout(original_content, message_limit=message_limit)
    chunk_bodies = split_reply_for_limits(
        reply_content,
        first_limit=layout.first_body_limit,
        continuation_limit=layout.continuation_body_limit,
    )
    return format_response_chunks(
        original_content,
        chunk_bodies,
        message_limit=message_limit,
    )
