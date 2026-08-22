"""Output sanitizer that strips chain-of-thought and reasoning artifacts."""

from __future__ import annotations

import re

from eva.constants import RESPONSE_WATERMARK

# Match <think>...</think> and <thinking>...</thinking> tags (case-insensitive, multiline)
_THINK_TAG_RE = re.compile(
    r"</?think(?:ing)?>.*?</think(?:ing)?>",
    re.DOTALL | re.IGNORECASE,
)

# Match self-closing or empty think tags
_THINK_EMPTY_RE = re.compile(
    r"</?think(?:ing)?\s*/>",
    re.IGNORECASE,
)

# Some providers expose their internal tool protocol as DSML text in the normal
# content field instead of returning structured ``tool_calls``. Never let that
# protocol markup reach Discord.
_DSML_TOOL_BLOCK_RE = re.compile(
    r"<(?:\||｜){2}DSML(?:\||｜){2}tool_calls\b[^>]*>.*?"
    r"(?:</(?:\||｜){2}DSML(?:\||｜){2}tool_calls\s*>|$)",
    re.DOTALL | re.IGNORECASE,
)
_DSML_TOOL_MARKER_RE = re.compile(
    r"<(?:\||｜){2}DSML(?:\||｜){2}(?:tool_calls|invoke|parameter)\b",
    re.IGNORECASE,
)

# Match lines that are purely separators (common reasoning artifact)
_SEPARATOR_LINE_RE = re.compile(r"^\s*---+\s*$", re.MULTILINE)

# Channel-context serialization the model sometimes echoes back as its own
# reply. Keep the required ``@Name (tag)`` shape narrow enough that ordinary
# mentions and speaker labels are left alone.
_TRANSCRIPT_LINE_RE = re.compile(
    r"^\s*(?:eva\s*:\s*)?"  # optional model-added "eva:" speaker label
    r"(?:\[\d{1,2}:\d{2}(?:\s+message_id:\d+)?\]\s+)?"
    r"@[^:\s()]+"  # @name
    r"(?:\s+\|\s+[^()\n|]+)*"  # optional " | sr:x" style segments
    r"\s*\([^()\n]*\)"  # (tag) — always present in serialized context
    r"(?:[^:\n]|:(?!\s))*"  # IDs and optional reply/attachment metadata
    r":\s*",
    re.IGNORECASE,
)

# Trailing "(mentions: @A (a); @B (b))" annotation copied from context lines.
_TRANSCRIPT_MENTIONS_TRAILER_RE = re.compile(
    r"\s*\(mentions?:\s+(?:[^()]|\([^()]*\))*\)\s*$",
)

# Keep this narrower than "all non-ASCII" so accented names and ASCII emoticons remain intact.
_EMOJI_RE = re.compile(
    "["
    "\\U0001F1E6-\\U0001F1FF"
    "\\U0001F300-\\U0001FAFF"
    "\\U00002600-\\U000027BF"
    "\\U00002300-\\U000023FF"
    "]"
)
_QUESTION_START_RE = re.compile(
    r"^(?:who|what|when|where|why|how|is|are|am|was|were|do|does|did|can|could|"
    r"will|would|should|have|has|had|may|might|shall)\b",
    re.IGNORECASE,
)


def sanitize_response(content: str) -> str:
    """Strip chain-of-thought / reasoning artifacts from AI output.

    Removes:
    - ``<think>...</think>`` and ``<thinking>...</thinking>`` tags (case-insensitive)
    - Self-closing ``<think/>`` / ``<thinking/>`` tags
    - Standalone ``---`` separator lines (common in reasoning output)

    Returns the cleaned content, or the original if no artifacts were found.
    """
    if not content:
        return content

    cleaned = strip_tool_call_markup(content)
    cleaned = _THINK_TAG_RE.sub("", cleaned)
    cleaned = _THINK_EMPTY_RE.sub("", cleaned)
    cleaned = _SEPARATOR_LINE_RE.sub("", cleaned)
    cleaned = _normalize_plain_punctuation(cleaned)
    cleaned = _ensure_question_marks(cleaned)

    # Collapse runs of 3+ blank lines to 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def strip_tool_call_markup(content: str) -> str:
    """Remove provider-specific DSML tool-call envelopes from model output."""
    if not content:
        return content

    cleaned = _DSML_TOOL_BLOCK_RE.sub("", content)
    marker = _DSML_TOOL_MARKER_RE.search(cleaned)
    if marker is not None:
        cleaned = cleaned[: marker.start()]
    return cleaned.strip()


def _normalize_plain_punctuation(content: str) -> str:
    """Remove decorative Unicode output while preserving fenced code blocks."""
    parts = re.split(r"(```.*?```)", content, flags=re.DOTALL)
    for index in range(0, len(parts), 2):
        parts[index] = parts[index].replace("—", ",").replace("–", "-")
        parts[index] = _EMOJI_RE.sub("", parts[index])
    return "".join(parts)


def _ensure_question_marks(content: str) -> str:
    """Add a question mark to obvious direct questions missing terminal punctuation."""
    parts = re.split(r"(```.*?```)", content, flags=re.DOTALL)
    for index in range(0, len(parts), 2):
        lines = parts[index].splitlines(keepends=True)
        for line_index, line in enumerate(lines):
            newline = "\n" if line.endswith("\n") else ""
            text = line[:-1] if newline else line
            candidate = re.sub(r"^(?:>\s*|[-*+]\s+|\d+[.)]\s+)+", "", text.strip())
            candidate = candidate.lstrip("`*_~ ")
            if not _QUESTION_START_RE.match(candidate):
                continue
            if not candidate or candidate.endswith((".", "!", "?", ":", ";")):
                continue
            lines[line_index] = f"{text}?{newline}"
        parts[index] = "".join(lines)
    return "".join(parts)


def strip_context_echo(content: str) -> str:
    """Strip echoed channel-context transcript framing from model output.

    The model sees identity-aware context lines such as
    ``[18:51 message_id:1] @eva (tag) [user_id:2]: ...`` and sometimes
    regurgitates that framing, occasionally prefixed with ``eva:``. Requiring
    the serialized ``@name (tag)`` shape keeps genuine mentions intact.
    """
    if not content:
        return content

    cleaned = "\n".join(_TRANSCRIPT_LINE_RE.sub("", line) for line in content.split("\n"))
    cleaned = _TRANSCRIPT_MENTIONS_TRAILER_RE.sub("", cleaned)
    return cleaned.strip()


def strip_response_watermark(content: str) -> str:
    """Remove any ``RESPONSE_WATERMARK`` lines from ``content``.

    The model sees Eva's watermarked replies in history/channel context and
    sometimes regurgitates the watermark itself. Callers that append the
    watermark must strip pre-existing copies first so exactly one remains.
    """
    if not content or RESPONSE_WATERMARK not in content:
        return content

    kept_lines = [
        line for line in content.split("\n") if line.strip() != RESPONSE_WATERMARK
    ]
    cleaned = "\n".join(kept_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
