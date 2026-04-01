from __future__ import annotations


class ChannelResponseStore:
    def __init__(self) -> None:
        self._store: dict[int, str] = {}

    def get(self, channel_id: int) -> str | None:
        return self._store.get(channel_id)

    def set(self, channel_id: int, response_id: str) -> None:
        self._store[channel_id] = response_id

    def clear(self, channel_id: int) -> None:
        self._store.pop(channel_id, None)
