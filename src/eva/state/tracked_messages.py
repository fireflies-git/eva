from __future__ import annotations

import json
import logging
from collections import OrderedDict
from pathlib import Path

from eva.constants import MAX_TRACKED_MESSAGES

logger = logging.getLogger(__name__)

DEFAULT_TRACKED_MESSAGES_PATH = Path("tracked_messages.json")


class TrackedMessageStore:
    def __init__(
        self,
        *,
        path: Path | None = DEFAULT_TRACKED_MESSAGES_PATH,
        max_size: int = MAX_TRACKED_MESSAGES,
    ) -> None:
        if max_size <= 0:
            raise ValueError("max_size must be positive")
        self._path = path
        self._max_size = max_size
        self._message_ids: OrderedDict[int, None] = OrderedDict()
        self._load()

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load tracked messages from %s", self._path)
            return
        if not isinstance(data, list):
            logger.warning("Tracked messages file %s is not a list; ignoring", self._path)
            return
        for raw_id in data[-self._max_size :]:
            try:
                self._message_ids[int(raw_id)] = None
            except (TypeError, ValueError):
                continue

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            self._path.write_text(
                json.dumps(list(self._message_ids.keys())) + "\n",
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save tracked messages to %s", self._path)

    def add(self, message_id: int) -> None:
        if message_id in self._message_ids:
            self._message_ids.move_to_end(message_id)
            self._save()
            return
        self._message_ids[message_id] = None
        if len(self._message_ids) > self._max_size:
            self._message_ids.popitem(last=False)
        self._save()

    def contains(self, message_id: int) -> bool:
        return message_id in self._message_ids
