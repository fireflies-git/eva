from __future__ import annotations


class TrackedMessageStore:
    def __init__(self) -> None:
        self._message_ids: set[int] = set()

    def add(self, message_id: int) -> None:
        self._message_ids.add(message_id)

    def contains(self, message_id: int) -> bool:
        return message_id in self._message_ids
