from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import discord

from eva.reminders.service import ReminderRunner
from eva.state.reminders import ReminderStore


class StubChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id
        self.sent: list[str] = []

    async def send(self, *, content: str) -> object:
        self.sent.append(content)
        return object()


class StubClient:
    def __init__(self) -> None:
        self.channels: dict[int, StubChannel] = {}

    def register(self, channel_id: int) -> StubChannel:
        channel = StubChannel(channel_id)
        self.channels[channel_id] = channel
        return channel

    def get_channel(self, channel_id: int):
        return self.channels.get(channel_id)


def test_fires_due_reminder_and_clears_store(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    client = StubClient()
    channel = client.register(99)

    past_time = datetime.now(UTC) - timedelta(seconds=5)
    store.add(user_id=42, channel_id=99, fire_at=past_time, text="ping me")

    runner = ReminderRunner(
        store=store,
        client_provider=lambda: cast(discord.Client, client),
    )
    asyncio.run(runner._fire_due_reminders())

    assert len(channel.sent) == 1
    assert "<@42>" in channel.sent[0]
    assert "ping me" in channel.sent[0]
    assert store.list_for_user(42) == []


def test_does_not_fire_future_reminder(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    client = StubClient()
    client.register(99)

    future_time = datetime.now(UTC) + timedelta(hours=1)
    store.add(user_id=42, channel_id=99, fire_at=future_time, text="later")

    runner = ReminderRunner(
        store=store,
        client_provider=lambda: cast(discord.Client, client),
    )
    asyncio.run(runner._fire_due_reminders())

    assert client.channels[99].sent == []
    assert len(store.list_for_user(42)) == 1


def test_skips_when_channel_unreachable(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    client = StubClient()
    # Channel 99 is NOT registered; client.get_channel returns None.

    past_time = datetime.now(UTC) - timedelta(seconds=5)
    store.add(user_id=42, channel_id=99, fire_at=past_time, text="ping me")

    runner = ReminderRunner(
        store=store,
        client_provider=lambda: cast(discord.Client, client),
    )
    asyncio.run(runner._fire_due_reminders())

    # The reminder is consumed (so we don't infinitely retry) but not delivered.
    assert store.list_for_user(42) == []


class FlakyStore:
    """pop_due blows up on the first tick, then behaves."""

    def __init__(self) -> None:
        self.calls = 0

    def pop_due(self, *, now: datetime) -> list[object]:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")
        return []


def test_runner_survives_tick_exception(tmp_path: Path) -> None:
    store = FlakyStore()
    runner = ReminderRunner(
        store=cast(ReminderStore, store),
        client_provider=lambda: None,
        check_interval_seconds=0.01,
    )

    async def run() -> None:
        runner.start()
        await asyncio.sleep(0.15)
        await runner.stop()

    asyncio.run(run())

    # A crashed tick must not kill the runner: it keeps polling afterwards.
    assert store.calls >= 2
