"""In-memory pending friend request decisions, keyed by requester."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from eva.constants import FRIEND_REQUEST_TTL_SECONDS


@dataclass(frozen=True, slots=True)
class PendingFriendRequest:
    requester_id: int
    requester_label: str
    review_text: str
    notified_admin_ids: frozenset[int]
    created_monotonic: float


class PendingFriendRequestStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = FRIEND_REQUEST_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._pending: dict[int, PendingFriendRequest] = {}

    def set(
        self,
        *,
        requester_id: int,
        requester_label: str,
        review_text: str,
        notified_admin_ids: frozenset[int],
    ) -> None:
        self._pending[requester_id] = PendingFriendRequest(
            requester_id=requester_id,
            requester_label=requester_label,
            review_text=review_text,
            notified_admin_ids=notified_admin_ids,
            created_monotonic=self._clock(),
        )

    def get(self, *, requester_id: int) -> PendingFriendRequest | None:
        pending = self._pending.get(requester_id)
        if pending is None:
            return None
        if self._is_expired(pending):
            self._pending.pop(requester_id, None)
            return None
        return pending

    def pop(self, *, requester_id: int) -> PendingFriendRequest | None:
        pending = self.get(requester_id=requester_id)
        if pending is None:
            return None
        self._pending.pop(requester_id, None)
        return pending

    def get_for_admin(
        self,
        *,
        requester_id: int,
        admin_user_id: int,
    ) -> PendingFriendRequest | None:
        pending = self.get(requester_id=requester_id)
        if pending is None or admin_user_id not in pending.notified_admin_ids:
            return None
        return pending

    def pop_for_admin(
        self,
        *,
        requester_id: int,
        admin_user_id: int,
    ) -> PendingFriendRequest | None:
        pending = self.get_for_admin(
            requester_id=requester_id,
            admin_user_id=admin_user_id,
        )
        if pending is None:
            return None
        self._pending.pop(requester_id, None)
        return pending

    def pop_oldest_for_admin(self, *, admin_user_id: int) -> PendingFriendRequest | None:
        """Pop the oldest pending request this admin was notified about.

        This is the "first admin reply wins" mechanism: when several requests
        are pending in one admin DM, the admin's yes/no resolves the oldest
        one they were asked about.
        """
        candidates: list[PendingFriendRequest] = []
        for requester_id, pending in list(self._pending.items()):
            if self._is_expired(pending):
                self._pending.pop(requester_id, None)
                continue
            if admin_user_id in pending.notified_admin_ids:
                candidates.append(pending)
        if not candidates:
            return None
        oldest = min(candidates, key=lambda pending: pending.created_monotonic)
        self._pending.pop(oldest.requester_id, None)
        return oldest

    def _is_expired(self, pending: PendingFriendRequest) -> bool:
        return self._clock() - pending.created_monotonic > self._ttl_seconds
