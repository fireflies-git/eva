"""Per-user persistent memory store."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_USER_MEMORY_PATH = Path("user_memory.json")
DEFAULT_MAX_NOTES_PER_USER = 20
DEFAULT_MAX_NOTE_CHARS = 500


class UserMemoryError(ValueError):
    """Raised for user-visible memory errors (note too long, capacity reached)."""


class UserMemoryPersistenceError(RuntimeError):
    """Raised when a memory mutation cannot be persisted to disk."""


class UserMemoryStore:
    def __init__(
        self,
        *,
        path: Path = DEFAULT_USER_MEMORY_PATH,
        max_notes_per_user: int = DEFAULT_MAX_NOTES_PER_USER,
        max_note_chars: int = DEFAULT_MAX_NOTE_CHARS,
    ) -> None:
        if max_notes_per_user <= 0:
            raise ValueError("max_notes_per_user must be positive")
        if max_note_chars <= 0:
            raise ValueError("max_note_chars must be positive")
        self._path = path
        self._max_notes_per_user = max_notes_per_user
        self._max_note_chars = max_note_chars
        self._notes: dict[int, list[str]] = {}
        self._load()

    @property
    def max_notes_per_user(self) -> int:
        return self._max_notes_per_user

    @property
    def max_note_chars(self) -> int:
        return self._max_note_chars

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load user memory from %s", self._path)
            return
        if not isinstance(data, dict):
            logger.warning("User memory file %s is not an object; ignoring", self._path)
            return
        for raw_user_id, raw_notes in data.items():
            try:
                user_id = int(raw_user_id)
            except (TypeError, ValueError):
                continue
            if not isinstance(raw_notes, list):
                continue
            cleaned = [str(note) for note in raw_notes if isinstance(note, str) and note.strip()]
            if cleaned:
                self._notes[user_id] = cleaned[: self._max_notes_per_user]

    def _save(self) -> bool:
        try:
            payload = {str(user_id): notes for user_id, notes in self._notes.items()}
            self._path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return True
        except Exception:
            logger.exception("Failed to save user memory to %s", self._path)
            return False

    def get(self, user_id: int) -> list[str]:
        return list(self._notes.get(user_id, ()))

    def add(self, user_id: int, note: str) -> str:
        cleaned = note.strip()
        if not cleaned:
            raise UserMemoryError("Memory note is empty.")
        if len(cleaned) > self._max_note_chars:
            raise UserMemoryError(
                f"Memory note is too long ({len(cleaned)} > {self._max_note_chars} chars)."
            )
        notes = self._notes.setdefault(user_id, [])
        if len(notes) >= self._max_notes_per_user:
            raise UserMemoryError(
                f"You already have {self._max_notes_per_user} memories. "
                "Forget one before adding more."
            )
        notes.append(cleaned)
        if not self._save():
            notes.pop()
            if not notes:
                self._notes.pop(user_id, None)
            raise UserMemoryPersistenceError(
                f"Failed to persist memory add for user_id={user_id}"
            )
        return cleaned

    def remove(self, user_id: int, index_1based: int) -> str | None:
        notes = self._notes.get(user_id)
        if not notes:
            return None
        if index_1based < 1 or index_1based > len(notes):
            return None
        removed = notes.pop(index_1based - 1)
        if not notes:
            self._notes.pop(user_id, None)
        if not self._save():
            # Re-insert at the original position to keep memory and disk in sync.
            self._notes.setdefault(user_id, []).insert(index_1based - 1, removed)
            raise UserMemoryPersistenceError(
                f"Failed to persist memory remove for user_id={user_id}"
            )
        return removed

    def clear(self, user_id: int) -> int:
        notes = self._notes.pop(user_id, None)
        if not notes:
            return 0
        if not self._save():
            self._notes[user_id] = notes
            raise UserMemoryPersistenceError(
                f"Failed to persist memory clear for user_id={user_id}"
            )
        return len(notes)
