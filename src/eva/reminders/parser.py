"""Duration and reminder-command parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta

_DURATION_PIECE_RE = re.compile(r"(\d+)\s*([wdhms])", re.IGNORECASE)
_UNIT_SECONDS = {
    "w": 7 * 24 * 60 * 60,
    "d": 24 * 60 * 60,
    "h": 60 * 60,
    "m": 60,
    "s": 1,
}


class ReminderParseError(ValueError):
    """Raised when a reminder command can't be parsed into a duration + text."""


@dataclass(frozen=True, slots=True)
class ParsedReminder:
    duration: timedelta
    text: str


def parse_duration(text: str) -> timedelta | None:
    """Parse a compact duration string like '2h30m', '90s', '1w', '45 min'.

    Returns None when the string contains no valid duration tokens.
    """
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None

    total_seconds = 0
    consumed_chars = 0
    for match in _DURATION_PIECE_RE.finditer(stripped):
        count = int(match.group(1))
        unit = match.group(2).lower()
        total_seconds += count * _UNIT_SECONDS[unit]
        consumed_chars += len(match.group(0))

    if total_seconds <= 0:
        return None

    # If the input had non-whitespace characters outside of duration tokens, reject it.
    leftover = _DURATION_PIECE_RE.sub("", stripped)
    if leftover.strip():
        return None

    return timedelta(seconds=total_seconds)


def format_duration(delta: timedelta) -> str:
    """Render a timedelta back into a compact string (e.g. '1d2h30m')."""
    total = int(delta.total_seconds())
    if total <= 0:
        return "0s"

    parts: list[str] = []
    for unit in ("w", "d", "h", "m", "s"):
        unit_seconds = _UNIT_SECONDS[unit]
        if total >= unit_seconds:
            value, total = divmod(total, unit_seconds)
            parts.append(f"{value}{unit}")
    return "".join(parts) or "0s"


def parse_reminder_command(remainder: str) -> ParsedReminder:
    """Parse the text *after* the trigger prefix + `remind`/`remindme` verb.

    Accepted shapes:
        `me in 2h to call mom`
        `me in 30m bring trash`
        `in 2h30m drink water`
        `2h call mom`

    Raises ReminderParseError when no duration is found or no text follows it.
    """
    if not remainder.strip():
        raise ReminderParseError("Usage: `remind me in <duration> to <text>`")

    text = remainder.strip()
    tokens = text.split()

    # Strip optional `me`, then optional `in`.
    if tokens and tokens[0].lower() == "me":
        tokens = tokens[1:]
    if tokens and tokens[0].lower() == "in":
        tokens = tokens[1:]

    # Greedy duration: consume tokens while they're duration-shaped.
    duration_tokens: list[str] = []
    while tokens:
        candidate = tokens[0]
        if parse_duration(candidate) is None and not _is_partial_duration_token(candidate):
            break
        duration_tokens.append(candidate)
        tokens = tokens[1:]

    if not duration_tokens:
        raise ReminderParseError(
            "I couldn't read the duration. Try `in 2h`, `30m`, `1d4h`, etc."
        )

    duration = parse_duration("".join(duration_tokens))
    if duration is None or duration.total_seconds() <= 0:
        raise ReminderParseError(
            "I couldn't read the duration. Try `in 2h`, `30m`, `1d4h`, etc."
        )

    # Strip optional leading "to "/"that ".
    if tokens and tokens[0].lower() in {"to", "that"}:
        tokens = tokens[1:]

    text_remainder = " ".join(tokens).strip()
    if not text_remainder:
        raise ReminderParseError("Tell me what to remind you about.")
    return ParsedReminder(duration=duration, text=text_remainder)


def _is_partial_duration_token(token: str) -> bool:
    return bool(_DURATION_PIECE_RE.search(token))
