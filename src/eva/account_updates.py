from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from eva.constants import CHECK_MARK, X_MARK

ACCOUNT_UPDATE_CONFIRMATION_TTL_SECONDS = 120.0
DISPLAY_NAME_MAX_CHARS = 32
BIO_MAX_CHARS = 190
CUSTOM_STATUS_MAX_CHARS = 128
VALID_PRESENCES = frozenset({"online", "idle", "dnd", "invisible"})


@dataclass(frozen=True, slots=True)
class AccountUpdateDraft:
    display_name: str | None = None
    clear_display_name: bool = False
    bio: str | None = None
    clear_bio: bool = False
    presence: str | None = None
    custom_status: str | None = None
    clear_custom_status: bool = False

    def has_changes(self) -> bool:
        return any(
            (
                self.display_name is not None,
                self.clear_display_name,
                self.bio is not None,
                self.clear_bio,
                self.presence is not None,
                self.custom_status is not None,
                self.clear_custom_status,
            )
        )


@dataclass(frozen=True, slots=True)
class AccountUpdatePlan:
    draft: AccountUpdateDraft | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PendingAccountUpdate:
    user_id: int
    channel_id: int
    draft: AccountUpdateDraft
    created_monotonic: float


class PendingAccountUpdateStore:
    def __init__(
        self,
        *,
        ttl_seconds: float = ACCOUNT_UPDATE_CONFIRMATION_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._pending: dict[tuple[int, int], PendingAccountUpdate] = {}

    def set(self, *, user_id: int, channel_id: int, draft: AccountUpdateDraft) -> None:
        self._pending[(user_id, channel_id)] = PendingAccountUpdate(
            user_id=user_id,
            channel_id=channel_id,
            draft=draft,
            created_monotonic=self._clock(),
        )

    def get(self, *, user_id: int, channel_id: int) -> PendingAccountUpdate | None:
        key = (user_id, channel_id)
        pending = self._pending.get(key)
        if pending is None:
            return None
        if self._is_expired(pending):
            self._pending.pop(key, None)
            return None
        return pending

    def pop(self, *, user_id: int, channel_id: int) -> PendingAccountUpdate | None:
        pending = self.get(user_id=user_id, channel_id=channel_id)
        if pending is None:
            return None
        self._pending.pop((user_id, channel_id), None)
        return pending

    def _is_expired(self, pending: PendingAccountUpdate) -> bool:
        return self._clock() - pending.created_monotonic > self._ttl_seconds


def validate_account_update_draft(draft: AccountUpdateDraft) -> str | None:
    if not draft.has_changes():
        return "No account changes were requested."
    if draft.display_name is not None and len(draft.display_name) > DISPLAY_NAME_MAX_CHARS:
        return (
            f"Display name is too long "
            f"({len(draft.display_name)} > {DISPLAY_NAME_MAX_CHARS} chars)."
        )
    if draft.bio is not None and len(draft.bio) > BIO_MAX_CHARS:
        return f"Bio is too long ({len(draft.bio)} > {BIO_MAX_CHARS} chars)."
    if draft.custom_status is not None and len(draft.custom_status) > CUSTOM_STATUS_MAX_CHARS:
        return (
            f"Custom status is too long "
            f"({len(draft.custom_status)} > {CUSTOM_STATUS_MAX_CHARS} chars)."
        )
    if draft.presence is not None and draft.presence not in VALID_PRESENCES:
        allowed = ", ".join(sorted(VALID_PRESENCES))
        return f"Presence must be one of: {allowed}."
    return None


def format_account_update_confirmation(draft: AccountUpdateDraft) -> str:
    lines = [f"{CHECK_MARK} Pending account update:"]
    lines.extend(f"- {line}" for line in describe_account_update_draft(draft))
    lines.append("")
    lines.append("Reply y to apply or n to cancel.")
    return "\n".join(lines)


def format_account_update_applied(draft: AccountUpdateDraft) -> str:
    lines = [f"{CHECK_MARK} Account update applied:"]
    lines.extend(f"- {line}" for line in describe_account_update_draft(draft))
    return "\n".join(lines)


def format_account_update_cancelled() -> str:
    return f"{X_MARK} Account update cancelled."


def describe_account_update_draft(draft: AccountUpdateDraft) -> list[str]:
    lines: list[str] = []
    if draft.display_name is not None:
        lines.append(f"Display name -> {draft.display_name!r}")
    elif draft.clear_display_name:
        lines.append("Display name -> cleared")

    if draft.bio is not None:
        lines.append(f"Bio -> {draft.bio!r}")
    elif draft.clear_bio:
        lines.append("Bio -> cleared")

    if draft.presence is not None:
        lines.append(f"Presence -> {draft.presence}")

    if draft.custom_status is not None:
        lines.append(f"Custom status -> {draft.custom_status!r}")
    elif draft.clear_custom_status:
        lines.append("Custom status -> cleared")

    return lines
