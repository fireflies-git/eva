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
