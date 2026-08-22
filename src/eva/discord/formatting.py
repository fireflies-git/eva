from __future__ import annotations

import random
import re
from dataclasses import dataclass

from eva.constants import DISCORD_MESSAGE_LIMIT, LOADING_MESSAGES, RESPONSE_WATERMARK, SPLIT_TRIGGER

EMPTY_RESPONSE = "(empty response)"
QUOTE_PREFIX = "> "
QUOTE_SEPARATOR = "\n "
CONTINUATION_PREFIX = "-# (cont.)\n "
_LIST_ITEM_RE = re.compile(r"^(?:[-*+]\s|\d+[.)]\s)")
_ABBREVIATION_RE = re.compile(r"(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|St|vs|e\.g|i\.e)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ResponseChunkLayout:
    safe_original: str
    first_prefix: str
    continuation_prefix: str
    first_body_limit: int
    continuation_body_limit: int


def build_loading_text(original_content: str) -> str:
    loading = random.choice(LOADING_MESSAGES)
    # Truncate like the response layout does so long prompts stay under the limit.
    safe_original = build_response_chunk_layout(original_content).safe_original
    return f"-# > {safe_original}\n {loading}"


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


def _split_section_into_sentences(section: str) -> list[str]:
    """Split prose at sentence endings without breaking inline code or URLs."""
    if section.startswith("```") and section.endswith("```"):
        return [section]

    sentences: list[str] = []
    start = 0
    inline_code = False
    index = 0
    while index < len(section):
        character = section[index]
        if character == "`":
            inline_code = not inline_code
            index += 1
            continue
        if inline_code or character not in ".!?":
            index += 1
            continue

        if character == "." and _is_non_sentence_period(section, index):
            index += 1
            continue

        end = index + 1
        while end < len(section) and section[end] in ".!?":
            end += 1
        if end == len(section) or section[end].isspace():
            sentence = section[start:end].strip()
            if sentence:
                sentences.append(sentence)
            start = end
        index = end

    remainder = section[start:].strip()
    if remainder:
        sentences.append(remainder)
    return sentences or [section.strip() or EMPTY_RESPONSE]


def _is_non_sentence_period(text: str, index: int) -> bool:
    """Return whether a period is part of a number, URL, or abbreviation."""
    previous_character = text[index - 1] if index else ""
    next_character = text[index + 1] if index + 1 < len(text) else ""
    if previous_character.isdigit() and next_character.isdigit():
        return True
    if next_character and not next_character.isspace():
        return True

    word_start = index
    while word_start > 0 and text[word_start - 1].isalpha():
        word_start -= 1
    word = text[word_start:index]
    return bool(_ABBREVIATION_RE.fullmatch(word))


def _split_into_message_units(text: str) -> list[str]:
    normalized = text.strip()
    watermark = ""
    if normalized.endswith(RESPONSE_WATERMARK):
        normalized = normalized[: -len(RESPONSE_WATERMARK)].rstrip()
        watermark = f"\n{RESPONSE_WATERMARK}"

    units: list[str] = []
    for section in _split_into_sections(normalized):
        units.extend(_split_section_into_sentences(section))
    if watermark and units:
        units[-1] = f"{units[-1]}{watermark}"
    if len(units) > 1:
        units = [_remove_terminal_period(unit) for unit in units]
    return units or [EMPTY_RESPONSE]


def _remove_terminal_period(text: str) -> str:
    """Keep split chat messages casual without removing question or exclamation marks."""
    watermark = ""
    body = text
    if body.endswith(f"\n{RESPONSE_WATERMARK}"):
        body = body[: -(len(RESPONSE_WATERMARK) + 1)].rstrip()
        watermark = f"\n{RESPONSE_WATERMARK}"

    if body.endswith("."):
        body = body[:-1].rstrip()
    return f"{body}{watermark}"


def split_reply_for_limits(
    reply_content: str,
    *,
    first_limit: int,
    continuation_limit: int,
) -> list[str]:
    sections = _split_into_message_units(reply_content)
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


def split_on_text_triggers(content: str) -> list[str]:
    """Split content at each SPLIT_TRIGGER boundary.

    Returns a list of non-empty segments. If no trigger is found,
    returns [content].
    """
    if SPLIT_TRIGGER not in content:
        return [content]
    parts = content.split(SPLIT_TRIGGER)
    segments = [part.strip() for part in parts if part.strip()]
    return segments or [EMPTY_RESPONSE]


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
    segments = split_on_text_triggers(reply_content)
    all_chunks: list[str] = []
    for segment in segments:
        segment_chunks = split_message_content(segment, message_limit=message_limit)
        all_chunks.extend(segment_chunks)
    return all_chunks


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
    chunk_bodies: list[str] = []
    for segment in split_on_text_triggers(reply_content):
        # Only the very first body gets the larger first-message room; every
        # later body (including the first of each new segment) is a continuation.
        first_limit = layout.continuation_body_limit if chunk_bodies else layout.first_body_limit
        chunk_bodies.extend(
            split_reply_for_limits(
                segment,
                first_limit=first_limit,
                continuation_limit=layout.continuation_body_limit,
            )
        )
    return format_response_chunks(
        original_content,
        chunk_bodies,
        message_limit=message_limit,
    )
