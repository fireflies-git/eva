"""Background runner that fires due reminders."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Callable
from datetime import UTC, datetime

import discord

from eva.state import Reminder, ReminderPersistenceError, ReminderStore

logger = logging.getLogger(__name__)

DEFAULT_CHECK_INTERVAL_SECONDS = 30.0
_REMINDER_EMOJI = "⏰"


class ReminderRunner:
    """Polls `ReminderStore` and delivers due reminders via the Discord client."""

    def __init__(
        self,
        *,
        store: ReminderStore,
        client_provider: Callable[[], discord.Client | None],
        check_interval_seconds: float = DEFAULT_CHECK_INTERVAL_SECONDS,
    ) -> None:
        if check_interval_seconds <= 0:
            raise ValueError("check_interval_seconds must be positive")
        self._store = store
        self._client_provider = client_provider
        self._check_interval = check_interval_seconds
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="reminder-runner")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        try:
            while not self._stop_event.is_set():
                await self._fire_due_reminders()
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._check_interval,
                    )
                except TimeoutError:
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Reminder runner crashed")

    async def _fire_due_reminders(self) -> None:
        try:
            due = self._store.pop_due(now=datetime.now(UTC))
        except ReminderPersistenceError:
            logger.warning("Failed to persist reminder firings; retrying next tick")
            return
        if not due:
            return
        client = self._client_provider()
        for reminder in due:
            await self._deliver(client, reminder)

    async def _deliver(self, client: discord.Client | None, reminder: Reminder) -> None:
        if client is None:
            logger.warning(
                "Dropping reminder %s: no Discord client available", reminder.id
            )
            return
        channel = await _resolve_channel(client, reminder.channel_id)
        if channel is None:
            logger.warning(
                "Dropping reminder %s: channel %s not reachable",
                reminder.id,
                reminder.channel_id,
            )
            return
        body = f"<@{reminder.user_id}> {_REMINDER_EMOJI} reminder: {reminder.text}"
        try:
            await channel.send(content=body)
        except Exception:
            logger.exception("Failed to deliver reminder %s", reminder.id)


async def _resolve_channel(
    client: discord.Client,
    channel_id: int,
) -> discord.abc.Messageable | None:
    channel = client.get_channel(channel_id)
    if channel is not None:
        return channel  # type: ignore[return-value]
    fetch_channel = getattr(client, "fetch_channel", None)
    if fetch_channel is None:
        return None
    try:
        fetched = await fetch_channel(channel_id)
    except Exception:
        logger.exception("Failed to fetch channel %s for reminder", channel_id)
        return None
    return fetched  # type: ignore[return-value]
