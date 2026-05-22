"""Persistent reminder store."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_REMINDERS_PATH = Path("reminders.json")
DEFAULT_MAX_REMINDERS_PER_USER = 25
DEFAULT_MAX_REMINDER_TEXT_CHARS = 500


class ReminderError(ValueError):
    """Raised for user-visible reminder errors (capacity, length, etc.)."""


class ReminderPersistenceError(RuntimeError):
    """Raised when a reminder mutation cannot be persisted to disk."""


@dataclass(frozen=True, slots=True)
class Reminder:
    id: int
    user_id: int
    channel_id: int
    fire_at_iso: str
    text: str

    @property
    def fire_at(self) -> datetime:
        return datetime.fromisoformat(self.fire_at_iso)


class ReminderStore:
    def __init__(
        self,
        *,
        path: Path = DEFAULT_REMINDERS_PATH,
        max_per_user: int = DEFAULT_MAX_REMINDERS_PER_USER,
        max_text_chars: int = DEFAULT_MAX_REMINDER_TEXT_CHARS,
    ) -> None:
        if max_per_user <= 0:
            raise ValueError("max_per_user must be positive")
        if max_text_chars <= 0:
            raise ValueError("max_text_chars must be positive")
        self._path = path
        self._max_per_user = max_per_user
        self._max_text_chars = max_text_chars
        self._reminders: dict[int, Reminder] = {}
        self._next_id = 1
        self._load()

    @property
    def max_per_user(self) -> int:
        return self._max_per_user

    @property
    def max_text_chars(self) -> int:
        return self._max_text_chars

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load reminders from %s", self._path)
            return
        if not isinstance(data, dict):
            logger.warning("Reminders file %s is not an object; ignoring", self._path)
            return
        next_id_raw = data.get("next_id")
        if isinstance(next_id_raw, int) and next_id_raw > 0:
            self._next_id = next_id_raw
        raw_items = data.get("reminders", [])
        if not isinstance(raw_items, list):
            return
        for raw in raw_items:
            reminder = _coerce_reminder(raw)
            if reminder is None:
                continue
            self._reminders[reminder.id] = reminder
            if reminder.id >= self._next_id:
                self._next_id = reminder.id + 1

    def _save(self) -> bool:
        try:
            payload = {
                "next_id": self._next_id,
                "reminders": [asdict(r) for r in self._reminders.values()],
            }
            self._path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return True
        except Exception:
            logger.exception("Failed to save reminders to %s", self._path)
            return False

    def add(
        self,
        *,
        user_id: int,
        channel_id: int,
        fire_at: datetime,
        text: str,
    ) -> Reminder:
        cleaned = text.strip()
        if not cleaned:
            raise ReminderError("Reminder text is empty.")
        if len(cleaned) > self._max_text_chars:
            raise ReminderError(
                f"Reminder text is too long ({len(cleaned)} > {self._max_text_chars} chars)."
            )
        if self._count_for_user(user_id) >= self._max_per_user:
            raise ReminderError(
                f"You already have {self._max_per_user} active reminders. "
                "Forget one before adding more."
            )

        normalized = _ensure_utc(fire_at)
        reminder = Reminder(
            id=self._next_id,
            user_id=user_id,
            channel_id=channel_id,
            fire_at_iso=normalized.isoformat(),
            text=cleaned,
        )
        self._next_id += 1
        self._reminders[reminder.id] = reminder
        if not self._save():
            del self._reminders[reminder.id]
            self._next_id -= 1
            raise ReminderPersistenceError(
                f"Failed to persist reminder add for user_id={user_id}"
            )
        return reminder

    def list_for_user(self, user_id: int) -> list[Reminder]:
        owned = [r for r in self._reminders.values() if r.user_id == user_id]
        owned.sort(key=lambda r: r.fire_at_iso)
        return owned

    def list_all(self) -> list[Reminder]:
        return sorted(self._reminders.values(), key=lambda r: r.fire_at_iso)

    def remove(self, *, user_id: int, reminder_id: int) -> Reminder | None:
        existing = self._reminders.get(reminder_id)
        if existing is None or existing.user_id != user_id:
            return None
        del self._reminders[reminder_id]
        if not self._save():
            self._reminders[reminder_id] = existing
            raise ReminderPersistenceError(
                f"Failed to persist reminder remove for user_id={user_id}"
            )
        return existing

    def pop_due(self, *, now: datetime) -> list[Reminder]:
        boundary = _ensure_utc(now)
        due = [r for r in self._reminders.values() if r.fire_at <= boundary]
        if not due:
            return []
        for reminder in due:
            del self._reminders[reminder.id]
        if not self._save():
            for reminder in due:
                self._reminders[reminder.id] = reminder
            raise ReminderPersistenceError("Failed to persist reminder firings")
        due.sort(key=lambda r: r.fire_at_iso)
        return due

    def _count_for_user(self, user_id: int) -> int:
        return sum(1 for r in self._reminders.values() if r.user_id == user_id)


def _coerce_reminder(raw: object) -> Reminder | None:
    if not isinstance(raw, dict):
        return None
    try:
        return Reminder(
            id=int(raw["id"]),
            user_id=int(raw["user_id"]),
            channel_id=int(raw["channel_id"]),
            fire_at_iso=str(raw["fire_at_iso"]),
            text=str(raw["text"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
