"""Whitelist store for allowing other users to interact with Eva."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_WHITELIST_PATH = Path("whitelist.db")
LEGACY_WHITELIST_JSON_NAME = "whitelist.json"

_CREATE_TABLE = "CREATE TABLE IF NOT EXISTS whitelist (user_id INTEGER PRIMARY KEY)"


class WhitelistPersistenceError(RuntimeError):
    """Raised when a whitelist mutation cannot be persisted."""


class WhitelistStore:
    """SQLite-backed whitelist with an in-memory cache for hot-path reads.

    Mutations commit to the database first and only then update the cache, so
    a failed write never diverges from what is on disk.
    """

    def __init__(self, path: Path = DEFAULT_WHITELIST_PATH) -> None:
        self._path = path
        try:
            self._connection = sqlite3.connect(path)
            with self._connection:
                self._connection.execute(_CREATE_TABLE)
            self._user_ids = {
                int(row[0])
                for row in self._connection.execute("SELECT user_id FROM whitelist")
            }
        except sqlite3.Error as exc:
            raise WhitelistPersistenceError(
                f"Failed to open whitelist database at {path}"
            ) from exc
        self._migrate_legacy_json()

    def close(self) -> None:
        self._connection.close()

    def add(self, user_id: int) -> bool:
        if user_id in self._user_ids:
            return False
        try:
            with self._connection:
                self._connection.execute(
                    "INSERT OR IGNORE INTO whitelist (user_id) VALUES (?)",
                    (user_id,),
                )
        except sqlite3.Error as exc:
            raise WhitelistPersistenceError(
                f"Failed to persist whitelist add for user_id={user_id}"
            ) from exc
        self._user_ids.add(user_id)
        return True

    def remove(self, user_id: int) -> bool:
        if user_id not in self._user_ids:
            return False
        try:
            with self._connection:
                self._connection.execute(
                    "DELETE FROM whitelist WHERE user_id = ?",
                    (user_id,),
                )
        except sqlite3.Error as exc:
            raise WhitelistPersistenceError(
                f"Failed to persist whitelist remove for user_id={user_id}"
            ) from exc
        self._user_ids.discard(user_id)
        return True

    def clear(self) -> int:
        count = len(self._user_ids)
        if count == 0:
            return 0
        try:
            with self._connection:
                self._connection.execute("DELETE FROM whitelist")
        except sqlite3.Error as exc:
            raise WhitelistPersistenceError("Failed to persist whitelist clear") from exc
        self._user_ids.clear()
        return count

    def contains(self, user_id: int) -> bool:
        return user_id in self._user_ids

    def list_all(self) -> list[int]:
        return sorted(self._user_ids)

    def _migrate_legacy_json(self) -> None:
        """One-time import of a legacy ``whitelist.json`` next to the database.

        Runs only when the database is empty, then renames the JSON file so a
        cleared whitelist cannot be resurrected on the next startup.
        """
        legacy_path = self._path.parent / LEGACY_WHITELIST_JSON_NAME
        if legacy_path == self._path or not legacy_path.exists():
            return
        if self._user_ids:
            return

        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read legacy whitelist %s", legacy_path)
            return
        if not isinstance(data, list):
            logger.warning("Legacy whitelist %s is not a list; skipping import", legacy_path)
            return

        user_ids: list[int] = []
        for raw_id in data:
            try:
                user_ids.append(int(raw_id))
            except (TypeError, ValueError):
                continue

        try:
            with self._connection:
                self._connection.executemany(
                    "INSERT OR IGNORE INTO whitelist (user_id) VALUES (?)",
                    [(user_id,) for user_id in user_ids],
                )
        except sqlite3.Error:
            logger.exception("Failed to import legacy whitelist %s", legacy_path)
            return
        self._user_ids.update(user_ids)

        try:
            legacy_path.rename(legacy_path.with_name(f"{legacy_path.name}.bak"))
        except OSError:
            logger.exception("Failed to rename legacy whitelist %s after import", legacy_path)
        logger.info("Migrated %d whitelist entries from %s", len(user_ids), legacy_path)
