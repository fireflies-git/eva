from __future__ import annotations

import time
from collections import deque
from typing import Protocol


class _MonotonicClock(Protocol):
    def __call__(self) -> float: ...


class RateLimiter:
    """Sliding-window per-user rate limiter.

    Each user gets up to `max_requests` consumptions inside any rolling
    `window_seconds` interval. Exempt user IDs bypass the limiter entirely.
    """

    def __init__(
        self,
        *,
        max_requests: int,
        window_seconds: float,
        exempt_user_ids: set[int] | None = None,
        clock: _MonotonicClock | None = None,
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._exempt: set[int] = set(exempt_user_ids or ())
        self._clock = clock or time.monotonic
        self._events: dict[int, deque[float]] = {}

    def is_exempt(self, user_id: int) -> bool:
        return user_id in self._exempt

    def check_and_consume(self, user_id: int) -> bool:
        if user_id in self._exempt:
            return True
        now = self._clock()
        events = self._events.setdefault(user_id, deque())
        cutoff = now - self._window_seconds
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= self._max_requests:
            return False
        events.append(now)
        return True
