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

# Match lines that are purely separators (common reasoning artifact)
_SEPARATOR_LINE_RE = re.compile(r"^\s*---+\s*$", re.MULTILINE)

# Channel-context serialization the model sometimes echoes back as its own
# reply: "[HH:MM] @Name (tag) reply to @X: ..." — the "(tag)" group is always
# present in the serializer output, so requiring it here keeps genuine
# "@name:" mentions intact.
_TRANSCRIPT_LINE_RE = re.compile(
    r"^\s*(?:\[\d{1,2}:\d{2}\]\s+)?"  # optional [HH:MM] timestamp
    r"@[^:\s()]+"  # @name
    r"(?:\s+\|\s+[^()\n|]+)*"  # optional " | sr:x" style segments
    r"\s*\([^()\n]*\)"  # (tag) — always present in serialized context
    r"[^:\n]*"  # optional extras (reply to @X, edited, ...)
    r":\s*",
)

# Trailing "(mentions: @A (a); @B (b))" annotation copied from context lines.
_TRANSCRIPT_MENTIONS_TRAILER_RE = re.compile(
    r"\s*\(mentions?:\s+(?:[^()]|\([^()]*\))*\)\s*$",
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

    cleaned = _THINK_TAG_RE.sub("", content)
    cleaned = _THINK_EMPTY_RE.sub("", cleaned)
    cleaned = _SEPARATOR_LINE_RE.sub("", cleaned)

    # Collapse runs of 3+ blank lines to 2
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def strip_context_echo(content: str) -> str:
    """Strip echoed channel-context transcript framing from model output.

    The model sees serialized context lines like
    ``[18:51] @eva (tag) reply to @user: ... (mentions: ...)`` and sometimes
    regurgitates the framing as its own message. The ``(tag)`` group is always
    present in the serializer, so requiring it here keeps genuine ``@name:``
    mentions intact.
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
