from __future__ import annotations

from collections import OrderedDict

from eva.constants import DEFAULT_MAX_CHANNEL_RESPONSES


class ChannelResponseStore:
    def __init__(self, *, max_channels: int = DEFAULT_MAX_CHANNEL_RESPONSES) -> None:
        self._max_channels = max(max_channels, 1)
        self._store: OrderedDict[int, str] = OrderedDict()

    def get(self, channel_id: int) -> str | None:
        value = self._store.get(channel_id)
        if value is None:
            return None
        self._store.move_to_end(channel_id)
        return value

    def set(self, channel_id: int, response_id: str) -> None:
        self._store[channel_id] = response_id
        self._store.move_to_end(channel_id)
        while len(self._store) > self._max_channels:
            self._store.popitem(last=False)

    def clear(self, channel_id: int) -> None:
        self._store.pop(channel_id, None)
