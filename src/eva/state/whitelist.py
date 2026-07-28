"""Whitelist store for allowing other users to interact with Eva."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from eva.state.atomic import write_text_atomic

logger = logging.getLogger(__name__)

DEFAULT_WHITELIST_PATH = Path("whitelist.json")


class WhitelistPersistenceError(RuntimeError):
    """Raised when a whitelist mutation cannot be persisted to disk."""


class WhitelistStore:
    def __init__(self, path: Path = DEFAULT_WHITELIST_PATH) -> None:
        self._path = path
        self._user_ids: set[int] = set()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load whitelist from %s", self._path)
            return
        if not isinstance(data, list):
            logger.warning("Whitelist file %s is not a list; ignoring", self._path)
            return
        for raw_id in data:
            try:
                self._user_ids.add(int(raw_id))
            except (TypeError, ValueError):
                continue

    def _save(self) -> bool:
        try:
            write_text_atomic(
                self._path,
                json.dumps(sorted(self._user_ids), indent=2) + "\n",
            )
            return True
        except Exception:
            logger.exception("Failed to save whitelist to %s", self._path)
            return False

    def add(self, user_id: int) -> bool:
        if user_id in self._user_ids:
            return False
        self._user_ids.add(user_id)
        if not self._save():
            self._user_ids.discard(user_id)
            raise WhitelistPersistenceError(
                f"Failed to persist whitelist add for user_id={user_id}"
            )
        return True

    def remove(self, user_id: int) -> bool:
        if user_id not in self._user_ids:
            return False
        self._user_ids.discard(user_id)
        if not self._save():
            self._user_ids.add(user_id)
            raise WhitelistPersistenceError(
                f"Failed to persist whitelist remove for user_id={user_id}"
            )
        return True

    def contains(self, user_id: int) -> bool:
        return user_id in self._user_ids

    def list_all(self) -> list[int]:
        return sorted(self._user_ids)
