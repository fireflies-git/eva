import json
from pathlib import Path

import pytest

from eva.state.whitelist import WhitelistPersistenceError, WhitelistStore


def test_add_and_contains(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.json")
    assert store.contains(123) is False
    assert store.add(123) is True
    assert store.contains(123) is True


def test_add_duplicate(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.json")
    assert store.add(123) is True
    assert store.add(123) is False
    assert store.contains(123) is True


def test_remove(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.json")
    store.add(123)
    assert store.remove(123) is True
    assert store.contains(123) is False


def test_remove_nonexistent(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.json")
    assert store.remove(999) is False


def test_list_all(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.json")
    store.add(300)
    store.add(100)
    store.add(200)
    assert store.list_all() == [100, 200, 300]


def test_persistence(tmp_path: Path) -> None:
    path = tmp_path / "whitelist.json"
    store = WhitelistStore(path)
    store.add(111)
    store.add(222)

    store2 = WhitelistStore(path)
    assert store2.contains(111) is True
    assert store2.contains(222) is True
    assert store2.list_all() == [111, 222]


def test_persistence_file_format(tmp_path: Path) -> None:
    path = tmp_path / "whitelist.json"
    store = WhitelistStore(path)
    store.add(42)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == [42]


def test_add_raises_and_reverts_when_save_fails(tmp_path: Path) -> None:
    # Use a directory in place of the file so write_text() fails.
    path = tmp_path / "whitelist.json"
    path.mkdir()
    store = WhitelistStore(path)

    with pytest.raises(WhitelistPersistenceError):
        store.add(123)

    assert store.contains(123) is False
    assert store.list_all() == []


def test_remove_raises_and_reverts_when_save_fails(tmp_path: Path) -> None:
    path = tmp_path / "whitelist.json"
    store = WhitelistStore(path)
    store.add(123)

    # Replace the file with a directory so subsequent writes fail.
    path.unlink()
    path.mkdir()

    with pytest.raises(WhitelistPersistenceError):
        store.remove(123)

    assert store.contains(123) is True
    assert store.list_all() == [123]
