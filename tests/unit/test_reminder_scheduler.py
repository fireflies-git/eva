import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

from eva.reminders import ReminderDetector, ReminderIntent, ReminderScheduler
from eva.state import Reminder, ReminderPersistenceError, ReminderStore

_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


class StubDetector:
    def __init__(self, *, intent: ReminderIntent | None) -> None:
        self.intent = intent
        self.calls: list[dict[str, object]] = []

    async def detect(self, **kwargs: object) -> ReminderIntent | None:
        self.calls.append(kwargs)
        return self.intent


class CapacityCappedStore:
    """Drop-in ReminderStore that always rejects with ReminderError."""

    def __init__(self) -> None:
        self.max_per_user = 25

    def add(self, **kwargs: object) -> Reminder:
        from eva.state import ReminderError

        raise ReminderError("You already have 25 active reminders.")


class PersistenceFailingStore:
    def __init__(self) -> None:
        self.max_per_user = 25

    def add(self, **kwargs: object) -> Reminder:
        raise ReminderPersistenceError("disk full")


def _make_store(tmp_path: Path) -> ReminderStore:
    return ReminderStore(path=tmp_path / "reminders.json")


def test_scheduler_returns_none_when_detector_returns_none(tmp_path: Path) -> None:
    scheduler = ReminderScheduler(
        detector=cast(ReminderDetector, StubDetector(intent=None)),
        store=_make_store(tmp_path),
    )
    result = asyncio.run(
        scheduler.schedule_if_needed(
            user_message="hey",
            user_id=1,
            channel_id=99,
            now=_NOW,
        )
    )
    assert result is None


def test_scheduler_schedules_and_returns_confirmation(tmp_path: Path) -> None:
    store = _make_store(tmp_path)
    intent = ReminderIntent(fire_at=_NOW + timedelta(minutes=5), text="take out trash")
    scheduler = ReminderScheduler(
        detector=cast(ReminderDetector, StubDetector(intent=intent)),
        store=store,
    )

    result = asyncio.run(
        scheduler.schedule_if_needed(
            user_message="remind me in 5m to take out trash",
            user_id=42,
            channel_id=99,
            now=_NOW,
        )
    )
    assert result is not None
    assert "Reminder #1" in result.content
    assert "5m" in result.content
    assert "take out trash" in result.content
    assert len(store.list_for_user(42)) == 1


def test_scheduler_surfaces_capacity_error() -> None:
    intent = ReminderIntent(fire_at=_NOW + timedelta(minutes=5), text="thing")
    scheduler = ReminderScheduler(
        detector=cast(ReminderDetector, StubDetector(intent=intent)),
        store=cast(ReminderStore, CapacityCappedStore()),
    )

    result = asyncio.run(
        scheduler.schedule_if_needed(
            user_message="remind me in 5m",
            user_id=1,
            channel_id=2,
            now=_NOW,
        )
    )
    assert result is not None
    assert "already have 25 active reminders" in result.content


def test_scheduler_handles_persistence_failure() -> None:
    intent = ReminderIntent(fire_at=_NOW + timedelta(minutes=5), text="thing")
    scheduler = ReminderScheduler(
        detector=cast(ReminderDetector, StubDetector(intent=intent)),
        store=cast(ReminderStore, PersistenceFailingStore()),
    )

    result = asyncio.run(
        scheduler.schedule_if_needed(
            user_message="remind me in 5m",
            user_id=1,
            channel_id=2,
            now=_NOW,
        )
    )
    assert result is not None
    assert "Couldn't save that reminder" in result.content
