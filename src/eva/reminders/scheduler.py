"""Glue between the AI reminder detector and the reminder store."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from eva.constants import CHECK_MARK, X_MARK
from eva.reminders.detector import ReminderDetector
from eva.reminders.parser import format_duration
from eva.state import ReminderError, ReminderPersistenceError, ReminderStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReminderConfirmation:
    content: str


class ReminderScheduler:
    """Runs the AI detector; on a positive hit, schedules and confirms."""

    def __init__(self, *, detector: ReminderDetector, store: ReminderStore) -> None:
        self._detector = detector
        self._store = store

    async def schedule_if_needed(
        self,
        *,
        user_message: str,
        user_id: int,
        channel_id: int,
        now: datetime | None = None,
    ) -> ReminderConfirmation | None:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        intent = await self._detector.detect(
            user_message=user_message,
            current_time=current,
        )
        if intent is None:
            return None

        try:
            reminder = self._store.add(
                user_id=user_id,
                channel_id=channel_id,
                fire_at=intent.fire_at,
                text=intent.text,
            )
        except ReminderError as exc:
            return ReminderConfirmation(content=f"{X_MARK} {exc}")
        except ReminderPersistenceError:
            logger.exception("Failed to persist auto-detected reminder")
            return ReminderConfirmation(
                content=f"{X_MARK} Couldn't save that reminder.",
            )

        duration = reminder.fire_at - current
        return ReminderConfirmation(
            content=(
                f"{CHECK_MARK} Reminder #{reminder.id} set for in "
                f"{format_duration(duration)} — \"{reminder.text}\""
            ),
        )
