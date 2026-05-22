from __future__ import annotations

from collections import OrderedDict, deque

from eva.ai.schemas import ChatMessage
from eva.constants import DEFAULT_MAX_CHANNEL_HISTORIES


class ChannelHistoryStore:
    def __init__(
        self,
        max_messages_per_channel: int = 20,
        *,
        max_channels: int = DEFAULT_MAX_CHANNEL_HISTORIES,
    ) -> None:
        self._max_messages_per_channel = max(max_messages_per_channel, 1)
        self._max_channels = max(max_channels, 1)
        self._store: OrderedDict[int, deque[ChatMessage]] = OrderedDict()

    def get(self, channel_id: int) -> list[ChatMessage]:
        history = self._store.get(channel_id)
        if history is None:
            return []
        self._store.move_to_end(channel_id)
        return list(history)

    def append(self, channel_id: int, role: str, content: str) -> None:
        self._touch_for_write(channel_id).append({"role": role, "content": content})

    def append_exchange(self, channel_id: int, user_content: str, assistant_content: str) -> None:
        self.append(channel_id, "user", user_content)
        self.append(channel_id, "assistant", assistant_content)

    def clear(self, channel_id: int) -> None:
        self._store.pop(channel_id, None)

    def _touch_for_write(self, channel_id: int) -> deque[ChatMessage]:
        history = self._store.get(channel_id)
        if history is None:
            history = deque(maxlen=self._max_messages_per_channel)
            self._store[channel_id] = history
            while len(self._store) > self._max_channels:
                self._store.popitem(last=False)
            return history
        self._store.move_to_end(channel_id)
        return history
