"""Persistent pending friend request decisions, keyed by requester."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eva.constants import FRIEND_REQUEST_TTL_SECONDS
from eva.state.atomic import write_text_atomic

logger = logging.getLogger(__name__)

DEFAULT_PENDING_FRIEND_REQUESTS_PATH = Path("pending_friend_requests.json")


@dataclass(frozen=True, slots=True)
class PendingFriendRequest:
    requester_id: int
    requester_label: str
    review_text: str
    notified_admin_ids: frozenset[int]
    created_monotonic: float
    created_at_epoch: float


class PendingFriendRequestStore:
    def __init__(
        self,
        *,
        path: Path | None = None,
        ttl_seconds: float = FRIEND_REQUEST_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._path = path
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._pending: dict[int, PendingFriendRequest] = {}
        self._load()

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
            created_at_epoch=time.time(),
        )
        self._save()

    def get(self, *, requester_id: int) -> PendingFriendRequest | None:
        pending = self._pending.get(requester_id)
        if pending is None:
            return None
        if self._is_expired(pending):
            self._pending.pop(requester_id, None)
            self._save()
            return None
        return pending

    def pop(self, *, requester_id: int) -> PendingFriendRequest | None:
        pending = self.get(requester_id=requester_id)
        if pending is None:
            return None
        self._pending.pop(requester_id, None)
        self._save()
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
        self._save()
        return pending

    def pop_latest_for_admin(self, *, admin_user_id: int) -> PendingFriendRequest | None:
        candidates = self._pending_for_admin(admin_user_id=admin_user_id)
        if not candidates:
            return None
        latest = max(candidates, key=lambda pending: pending.created_monotonic)
        self._pending.pop(latest.requester_id, None)
        self._save()
        return latest

    def list_pending(self) -> list[PendingFriendRequest]:
        for requester_id, pending in list(self._pending.items()):
            if self._is_expired(pending):
                self._pending.pop(requester_id, None)
        self._save()
        return list(self._pending.values())

    def add_notified_admins(
        self,
        *,
        requester_id: int,
        admin_ids: frozenset[int],
    ) -> None:
        pending = self.get(requester_id=requester_id)
        if pending is None:
            return
        self._pending[requester_id] = PendingFriendRequest(
            requester_id=pending.requester_id,
            requester_label=pending.requester_label,
            review_text=pending.review_text,
            notified_admin_ids=pending.notified_admin_ids | admin_ids,
            created_monotonic=pending.created_monotonic,
            created_at_epoch=pending.created_at_epoch,
        )
        self._save()

    def pop_oldest_for_admin(self, *, admin_user_id: int) -> PendingFriendRequest | None:
        """Pop the oldest pending request this admin was notified about.

        This is the "first admin reply wins" mechanism: when several requests
        are pending in one admin DM, the admin's yes/no resolves the oldest
        one they were asked about.
        """
        candidates = self._pending_for_admin(admin_user_id=admin_user_id)
        if not candidates:
            return None
        oldest = min(candidates, key=lambda pending: pending.created_monotonic)
        self._pending.pop(oldest.requester_id, None)
        self._save()
        return oldest

    def _pending_for_admin(self, *, admin_user_id: int) -> list[PendingFriendRequest]:
        candidates: list[PendingFriendRequest] = []
        expired = False
        for requester_id, pending in list(self._pending.items()):
            if self._is_expired(pending):
                self._pending.pop(requester_id, None)
                expired = True
                continue
            if admin_user_id in pending.notified_admin_ids:
                candidates.append(pending)
        if expired:
            self._save()
        return candidates

    def _load(self) -> None:
        if self._path is None or not self._path.exists():
            return
        try:
            raw_items = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load pending friend requests from %s", self._path)
            return
        if not isinstance(raw_items, list):
            logger.warning("Pending friend requests file %s is not a list", self._path)
            return

        now_epoch = time.time()
        for raw_item in raw_items:
            pending = _coerce_pending_request(raw_item, now_epoch=now_epoch, clock=self._clock)
            if pending is None or self._is_expired(pending):
                continue
            self._pending[pending.requester_id] = pending

    def _save(self) -> None:
        if self._path is None:
            return
        try:
            payload = [
                {
                    "requester_id": pending.requester_id,
                    "requester_label": pending.requester_label,
                    "review_text": pending.review_text,
                    "notified_admin_ids": sorted(pending.notified_admin_ids),
                    "created_at_epoch": pending.created_at_epoch,
                }
                for pending in self._pending.values()
            ]
            write_text_atomic(self._path, json.dumps(payload, indent=2) + "\n")
        except Exception:
            logger.exception("Failed to save pending friend requests to %s", self._path)

    def _is_expired(self, pending: PendingFriendRequest) -> bool:
        return self._clock() - pending.created_monotonic > self._ttl_seconds


def _coerce_pending_request(
    raw_item: object,
    *,
    now_epoch: float,
    clock: Callable[[], float],
) -> PendingFriendRequest | None:
    if not isinstance(raw_item, dict):
        return None
    requester_id = raw_item.get("requester_id")
    requester_label = raw_item.get("requester_label")
    review_text = raw_item.get("review_text")
    notified_admin_ids = raw_item.get("notified_admin_ids")
    created_at_epoch = raw_item.get("created_at_epoch")
    if not isinstance(requester_id, int) or requester_id <= 0:
        return None
    if not isinstance(requester_label, str) or not isinstance(review_text, str):
        return None
    if not isinstance(notified_admin_ids, list):
        return None
    if not isinstance(created_at_epoch, (int, float)):
        return None
    admin_ids = frozenset(
        item for item in notified_admin_ids if isinstance(item, int) and item > 0
    )
    elapsed = max(now_epoch - float(created_at_epoch), 0.0)
    return PendingFriendRequest(
        requester_id=requester_id,
        requester_label=requester_label,
        review_text=review_text,
        notified_admin_ids=admin_ids,
        created_monotonic=clock() - elapsed,
        created_at_epoch=float(created_at_epoch),
    )
