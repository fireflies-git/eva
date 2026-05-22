import json
from pathlib import Path

import pytest

from eva.state.user_memory import (
    UserMemoryError,
    UserMemoryPersistenceError,
    UserMemoryStore,
)


def test_add_and_get(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    assert store.get(1) == []
    store.add(1, "  hello world  ")
    assert store.get(1) == ["hello world"]


def test_remove_by_index(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    store.add(1, "first")
    store.add(1, "second")
    assert store.remove(1, 1) == "first"
    assert store.get(1) == ["second"]


def test_remove_out_of_range_returns_none(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    store.add(1, "one")
    assert store.remove(1, 0) is None
    assert store.remove(1, 5) is None
    assert store.remove(2, 1) is None


def test_clear(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    store.add(1, "a")
    store.add(1, "b")
    assert store.clear(1) == 2
    assert store.get(1) == []
    assert store.clear(1) == 0


def test_rejects_empty_note(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    with pytest.raises(UserMemoryError):
        store.add(1, "   ")


def test_rejects_overlong_note(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json", max_note_chars=10)
    with pytest.raises(UserMemoryError):
        store.add(1, "a" * 11)


def test_capacity_enforced(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json", max_notes_per_user=2)
    store.add(1, "one")
    store.add(1, "two")
    with pytest.raises(UserMemoryError):
        store.add(1, "three")


def test_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    store = UserMemoryStore(path=path)
    store.add(1, "remember this")
    store.add(2, "and this")

    reopened = UserMemoryStore(path=path)
    assert reopened.get(1) == ["remember this"]
    assert reopened.get(2) == ["and this"]


def test_persistence_file_format(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    store = UserMemoryStore(path=path)
    store.add(1, "alpha")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {"1": ["alpha"]}


def test_load_tolerates_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.write_text("not json", encoding="utf-8")
    store = UserMemoryStore(path=path)
    assert store.get(1) == []


def test_add_raises_and_reverts_when_save_fails(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    path.mkdir()
    store = UserMemoryStore(path=path)
    with pytest.raises(UserMemoryPersistenceError):
        store.add(1, "note")
    assert store.get(1) == []


def test_remove_raises_and_reverts_when_save_fails(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    store = UserMemoryStore(path=path)
    store.add(1, "stay")

    path.unlink()
    path.mkdir()

    with pytest.raises(UserMemoryPersistenceError):
        store.remove(1, 1)
    assert store.get(1) == ["stay"]


def test_clear_raises_and_reverts_when_save_fails(tmp_path: Path) -> None:
    path = tmp_path / "memory.json"
    store = UserMemoryStore(path=path)
    store.add(1, "stay")

    path.unlink()
    path.mkdir()

    with pytest.raises(UserMemoryPersistenceError):
        store.clear(1)
    assert store.get(1) == ["stay"]
