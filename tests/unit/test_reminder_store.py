import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from eva.state.reminders import (
    ReminderError,
    ReminderPersistenceError,
    ReminderStore,
)


def _utc(seconds_from_now: float) -> datetime:
    return datetime.now(UTC) + timedelta(seconds=seconds_from_now)


def test_add_assigns_increasing_ids(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    a = store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="first")
    b = store.add(user_id=1, channel_id=10, fire_at=_utc(120), text="second")
    assert b.id == a.id + 1


def test_list_for_user_is_sorted_and_isolated(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    store.add(user_id=1, channel_id=10, fire_at=_utc(120), text="later")
    store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="sooner")
    store.add(user_id=2, channel_id=10, fire_at=_utc(30), text="other user")
    items = store.list_for_user(1)
    assert [r.text for r in items] == ["sooner", "later"]


def test_remove_only_by_owner(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    reminder = store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="x")
    assert store.remove(user_id=2, reminder_id=reminder.id) is None
    removed = store.remove(user_id=1, reminder_id=reminder.id)
    assert removed is not None
    assert store.list_for_user(1) == []


def test_pop_due_returns_and_clears(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    store.add(user_id=1, channel_id=10, fire_at=_utc(-5), text="past")
    store.add(user_id=1, channel_id=10, fire_at=_utc(600), text="future")
    fired = store.pop_due(now=datetime.now(UTC))
    assert [r.text for r in fired] == ["past"]
    assert [r.text for r in store.list_for_user(1)] == ["future"]


def test_rejects_empty_or_overlong_text(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json", max_text_chars=10)
    with pytest.raises(ReminderError):
        store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="   ")
    with pytest.raises(ReminderError):
        store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="x" * 11)


def test_capacity_enforced(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json", max_per_user=2)
    store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="a")
    store.add(user_id=1, channel_id=10, fire_at=_utc(120), text="b")
    with pytest.raises(ReminderError):
        store.add(user_id=1, channel_id=10, fire_at=_utc(180), text="c")


def test_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "reminders.json"
    store = ReminderStore(path=path)
    saved = store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="persist me")

    reopened = ReminderStore(path=path)
    items = reopened.list_for_user(1)
    assert len(items) == 1
    assert items[0].id == saved.id
    assert items[0].text == "persist me"


def test_next_id_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "reminders.json"
    store = ReminderStore(path=path)
    first = store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="a")

    reopened = ReminderStore(path=path)
    second = reopened.add(user_id=1, channel_id=10, fire_at=_utc(120), text="b")
    assert second.id == first.id + 1


def test_load_tolerates_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "reminders.json"
    path.write_text("not json", encoding="utf-8")
    store = ReminderStore(path=path)
    assert store.list_all() == []
    # New reminders still save normally.
    store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="ok")
    assert len(store.list_all()) == 1


def test_add_raises_and_reverts_when_save_fails(tmp_path: Path) -> None:
    path = tmp_path / "reminders.json"
    path.mkdir()
    store = ReminderStore(path=path)
    with pytest.raises(ReminderPersistenceError):
        store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="x")
    assert store.list_all() == []


def test_naive_datetime_normalized_to_utc(tmp_path: Path) -> None:
    store = ReminderStore(path=tmp_path / "reminders.json")
    naive = (datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None)
    reminder = store.add(user_id=1, channel_id=10, fire_at=naive, text="x")
    # Stored ISO string must be tz-aware so future loads can compare.
    assert reminder.fire_at.tzinfo is not None


def test_persistence_file_format(tmp_path: Path) -> None:
    path = tmp_path / "reminders.json"
    store = ReminderStore(path=path)
    store.add(user_id=1, channel_id=10, fire_at=_utc(60), text="x")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "next_id" in payload
    assert isinstance(payload["reminders"], list)
    assert payload["reminders"][0]["text"] == "x"
