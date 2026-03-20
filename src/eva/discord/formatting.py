from __future__ import annotations

import random

from eva.constants import DISCORD_MESSAGE_LIMIT, LOADING_MESSAGES


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


def split_message_content(
    text: str,
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    normalized = text.strip() or "(empty response)"
    if len(normalized) <= message_limit:
        return [normalized]

    chunks: list[str] = []
    remainder = normalized
    while remainder:
        if len(remainder) <= message_limit:
            chunks.append(remainder)
            break
        chunk, remainder = _take_chunk(remainder, message_limit)
        chunks.append(chunk)

    return chunks


def build_response_chunks(
    original_content: str,
    reply_content: str,
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    prefix = "-# > "
    separator = "\n "
    continuation_prefix = "-# (cont.)\n "

    safe_original = original_content
    max_original_len = message_limit - len(prefix) - len(separator) - 120
    if max_original_len < 0:
        max_original_len = 0
    if len(safe_original) > max_original_len:
        if max_original_len > 3:
            safe_original = safe_original[: max_original_len - 3] + "..."
        else:
            safe_original = ""

    first_prefix = f"{prefix}{safe_original}{separator}"
    first_room = message_limit - len(first_prefix)
    if first_room <= 0:
        first_room = 1

    normalized_reply = reply_content.strip() or "(empty response)"
    first_chunk_body, remainder = _take_chunk(normalized_reply, first_room)
    chunks = [f"{first_prefix}{first_chunk_body}"]

    continuation_room = message_limit - len(continuation_prefix)
    if continuation_room <= 0:
        return chunks

    while remainder:
        continuation_body, remainder = _take_chunk(remainder, continuation_room)
        chunks.append(f"{continuation_prefix}{continuation_body}")

    return chunks


def build_plain_response_chunks(
    reply_content: str,
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> list[str]:
    return split_message_content(reply_content, message_limit=message_limit)
