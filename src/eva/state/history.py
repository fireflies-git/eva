from __future__ import annotations

from collections import defaultdict, deque

from eva.ai.schemas import ChatMessage


class ChannelHistoryStore:
    def __init__(self, max_messages_per_channel: int = 20) -> None:
        self._store: dict[int, deque[ChatMessage]] = defaultdict(
            lambda: deque(maxlen=max_messages_per_channel)
        )

    def get(self, channel_id: int) -> list[ChatMessage]:
        return list(self._store[channel_id])

    def append(self, channel_id: int, role: str, content: str) -> None:
        self._store[channel_id].append({"role": role, "content": content})

    def append_exchange(self, channel_id: int, user_content: str, assistant_content: str) -> None:
        self.append(channel_id, "user", user_content)
        self.append(channel_id, "assistant", assistant_content)

    def clear(self, channel_id: int) -> None:
        self._store.pop(channel_id, None)
