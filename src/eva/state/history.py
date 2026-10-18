from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Callable

from eva.ai.schemas import ChatMessage
from eva.constants import DEFAULT_MAX_CHANNEL_HISTORIES


class ChannelHistoryStore:
    def __init__(
        self,
        max_messages_per_channel: int = 20,
        *,
        max_channels: int = DEFAULT_MAX_CHANNEL_HISTORIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_messages_per_channel = max(max_messages_per_channel, 1)
        self._max_channels = max(max_channels, 1)
        self._clock = clock
        self._store: OrderedDict[int, deque[tuple[float, ChatMessage]]] = OrderedDict()

    def get(self, channel_id: int, *, max_age_seconds: float | None = None) -> list[ChatMessage]:
        history = self._store.get(channel_id)
        if history is None:
            return []
        self._store.move_to_end(channel_id)
        if max_age_seconds is None:
            return [message for _, message in history]
        cutoff = self._clock() - max_age_seconds
        return [message for stored_at, message in history if stored_at >= cutoff]

    def append(self, channel_id: int, role: str, content: str) -> None:
        self._touch_for_write(channel_id).append(
            (self._clock(), {"role": role, "content": content})
        )

    def append_exchange(self, channel_id: int, user_content: str, assistant_content: str) -> None:
        self.append(channel_id, "user", user_content)
        self.append(channel_id, "assistant", assistant_content)

    def clear(self, channel_id: int) -> None:
        self._store.pop(channel_id, None)

    def _touch_for_write(self, channel_id: int) -> deque[tuple[float, ChatMessage]]:
        history = self._store.get(channel_id)
        if history is None:
            history = deque(maxlen=self._max_messages_per_channel)
            self._store[channel_id] = history
            while len(self._store) > self._max_channels:
                self._store.popitem(last=False)
            return history
        self._store.move_to_end(channel_id)
        return history
