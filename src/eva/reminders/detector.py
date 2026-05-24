"""AI-driven reminder detection.

Decides whether a triggered Discord message is a natural-language reminder
request ("ping me in 5m", "remind me tomorrow at 9 about the meeting", etc.)
and, if so, extracts when it should fire and what text to deliver.

A cheap regex gate filters obvious non-reminder messages before any AI call.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime

from eva.ai.client import AIClientError, ChatCompletionClient
from eva.prompts import build_reminder_detection_prompt

logger = logging.getLogger(__name__)

_DETECTION_MAX_TOKENS = 200

_HEURISTIC_RE = re.compile(
    r"\b("
    r"remind|reminder|"
    r"ping\s+me|alert\s+me|notify\s+me|wake\s+me|"
    r"don'?t\s+let\s+me\s+forget|"
    r"in\s+\d+\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|"
    r"hour|hours|d|day|days|w|week|weeks)|"
    r"after\s+\d+\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|"
    r"hour|hours|d|day|days|w|week|weeks)|"
    r"\d+\s*(?:s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|"
    r"hour|hours|d|day|days|w|week|weeks)\s+(?:from\s+now|later)|"
    r"at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?|"
    r"tomorrow|tonight|"
    r"this\s+(?:morning|afternoon|evening|weekend)|"
    r"next\s+(?:week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r")\b",
    re.IGNORECASE,
)


def looks_like_reminder(text: str) -> bool:
    """Cheap heuristic to skip the AI call on obvious non-reminder messages."""
    if not text:
        return False
    return _HEURISTIC_RE.search(text) is not None


@dataclass(frozen=True, slots=True)
class ReminderIntent:
    fire_at: datetime
    text: str


class ReminderDetector:
    def __init__(self, *, client: ChatCompletionClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def detect(
        self,
        *,
        user_message: str,
        current_time: datetime,
    ) -> ReminderIntent | None:
        message = user_message.strip()
        if not message:
            return None
        if not looks_like_reminder(message):
            return None

        anchor = _ensure_utc(current_time)
        prompt = build_reminder_detection_prompt(current_time_iso=anchor.isoformat())

        try:
            response = await self._client.chat_completion(
                messages=[
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": message},
                ],
                model=self._model_name,
                temperature=0.0,
                max_tokens=_DETECTION_MAX_TOKENS,
            )
        except AIClientError:
            logger.exception("Reminder detection AI call failed")
            return None

        return _parse_detection_response(response, now=anchor)


def _parse_detection_response(raw: str, *, now: datetime) -> ReminderIntent | None:
    payload = _extract_json_object(raw)
    if payload is None:
        return None

    if payload.get("is_reminder") is not True:
        return None

    fire_at_raw = payload.get("fire_at_iso")
    text_raw = payload.get("text")
    if not isinstance(fire_at_raw, str) or not isinstance(text_raw, str):
        return None

    cleaned_text = text_raw.strip()
    if not cleaned_text:
        return None

    try:
        parsed = datetime.fromisoformat(fire_at_raw.replace("Z", "+00:00"))
    except ValueError:
        return None

    fire_at = _ensure_utc(parsed)
    if fire_at <= now:
        return None

    return ReminderIntent(fire_at=fire_at, text=cleaned_text)


def _extract_json_object(raw: str) -> dict[str, object] | None:
    text = raw.strip()
    if not text:
        return None
    text = _strip_code_fence(text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Fall back to scanning for the first balanced {...} object.
        candidate = _first_json_object(text)
        if candidate is None:
            return None
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return None

    if not isinstance(data, dict):
        return None
    return data


def _strip_code_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
