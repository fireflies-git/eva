from __future__ import annotations

import time
from collections import deque
from typing import Protocol

# When the events dict grows past this many users, empty deques are pruned
# so one-time users don't accumulate forever.
_PRUNE_THRESHOLD_USERS = 1000


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
        if len(self._events) > _PRUNE_THRESHOLD_USERS:
            self._prune_expired(now)
        events = self._events.setdefault(user_id, deque())
        cutoff = now - self._window_seconds
        while events and events[0] < cutoff:
            events.popleft()
        if len(events) >= self._max_requests:
            return False
        events.append(now)
        return True

    def _prune_expired(self, now: float) -> None:
        cutoff = now - self._window_seconds
        stale_users: list[int] = []
        for user_id, events in self._events.items():
            while events and events[0] < cutoff:
                events.popleft()
            if not events:
                stale_users.append(user_id)
        for user_id in stale_users:
            del self._events[user_id]
