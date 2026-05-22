from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import discord

from eva.discord.reminder_commands import handle_reminder_command
from eva.state.reminders import ReminderStore


def _make_message(*, author_id: int = 1, channel_id: int = 10) -> discord.Message:
    return cast(
        discord.Message,
        SimpleNamespace(
            id=99,
            author=SimpleNamespace(id=author_id),
            channel=SimpleNamespace(id=channel_id),
            reference=None,
        ),
    )


def _run(coro):
    return asyncio.run(coro)


def test_remind_schedules_a_reminder(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    response = _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva remind me in 2h to call mom",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    assert response.handled is True
    assert "Reminder #" in response.content
    items = store.list_for_user(1)
    assert len(items) == 1
    assert items[0].text == "call mom"
    assert items[0].channel_id == 10


def test_remind_alias_with_no_text_returns_usage(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    response = _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva remind",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    assert response.handled is True
    assert "Usage" in response.content


def test_remind_with_bad_duration(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    response = _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva remind me to do thing",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    assert response.handled is True
    assert "duration" in response.content.lower()
    assert store.list_for_user(1) == []


def test_list_reminders_empty(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    response = _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva reminders",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    assert response.handled is True
    assert "no active reminders" in response.content.lower()


def test_list_reminders_shows_items(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva remind me in 1h thing",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    response = _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva reminders",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    assert response.handled is True
    assert "#1" in response.content
    assert "thing" in response.content


def test_forget_reminder_by_id(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva remind me in 1h trash",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    response = _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva forget reminder 1",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    assert response.handled is True
    assert "Forgot reminder #1" in response.content
    assert store.list_for_user(1) == []


def test_forget_reminder_for_someone_else_does_not_match(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    _run(
        handle_reminder_command(
            message=_make_message(author_id=1),
            content="eva remind me in 1h trash",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    response = _run(
        handle_reminder_command(
            message=_make_message(author_id=2),
            content="eva forget reminder 1",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    assert response.handled is True
    assert "No reminder #1" in response.content


def test_unrelated_message_not_handled(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    response = _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva hello",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    assert response.handled is False


def test_bare_forget_does_not_match(tmp_path: Path) -> None:
    # Bare `forget <N>` belongs to memory commands, not reminders.
    store = ReminderStore(path=tmp_path / "reminders.json")
    response = _run(
        handle_reminder_command(
            message=_make_message(),
            content="eva forget 3",
            trigger_prefix="eva ",
            reminder_store=store,
        )
    )
    assert response.handled is False
