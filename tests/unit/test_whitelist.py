import json
from pathlib import Path

import pytest

from eva.state.whitelist import WhitelistPersistenceError, WhitelistStore


def test_add_and_contains(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.db")
    assert store.contains(123) is False
    assert store.add(123) is True
    assert store.contains(123) is True


def test_add_duplicate(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.db")
    assert store.add(123) is True
    assert store.add(123) is False
    assert store.contains(123) is True


def test_remove(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.db")
    store.add(123)
    assert store.remove(123) is True
    assert store.contains(123) is False


def test_remove_nonexistent(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.db")
    assert store.remove(999) is False


def test_list_all(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.db")
    store.add(300)
    store.add(100)
    store.add(200)
    assert store.list_all() == [100, 200, 300]


def test_persistence(tmp_path: Path) -> None:
    path = tmp_path / "whitelist.db"
    store = WhitelistStore(path)
    store.add(111)
    store.add(222)
    store.close()

    store2 = WhitelistStore(path)
    assert store2.contains(111) is True
    assert store2.contains(222) is True
    assert store2.list_all() == [111, 222]


def test_clear_removes_all_entries_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "whitelist.db"
    store = WhitelistStore(path)
    store.add(111)
    store.add(222)

    assert store.clear() == 2
    assert store.list_all() == []
    store.close()

    store2 = WhitelistStore(path)
    assert store2.list_all() == []


def test_clear_on_empty_store_returns_zero(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.db")
    assert store.clear() == 0


def test_constructor_raises_when_database_unopenable(tmp_path: Path) -> None:
    with pytest.raises(WhitelistPersistenceError):
        WhitelistStore(tmp_path)


def test_add_raises_and_reverts_when_write_fails(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.db")
    store.close()

    with pytest.raises(WhitelistPersistenceError):
        store.add(123)

    assert store.contains(123) is False
    assert store.list_all() == []


def test_remove_raises_and_reverts_when_write_fails(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.db")
    store.add(123)
    store.close()

    with pytest.raises(WhitelistPersistenceError):
        store.remove(123)

    assert store.contains(123) is True
    assert store.list_all() == [123]


def test_clear_raises_and_reverts_when_write_fails(tmp_path: Path) -> None:
    store = WhitelistStore(tmp_path / "whitelist.db")
    store.add(123)
    store.close()

    with pytest.raises(WhitelistPersistenceError):
        store.clear()

    assert store.contains(123) is True


def test_migrates_legacy_json_into_database(tmp_path: Path) -> None:
    legacy_path = tmp_path / "whitelist.json"
    legacy_path.write_text(json.dumps([111, 222]), encoding="utf-8")

    store = WhitelistStore(tmp_path / "whitelist.db")

    assert store.list_all() == [111, 222]
    assert not legacy_path.exists()
    assert (tmp_path / "whitelist.json.bak").exists()


def test_migration_renames_json_so_cleared_whitelist_stays_cleared(tmp_path: Path) -> None:
    path = tmp_path / "whitelist.db"
    legacy_path = tmp_path / "whitelist.json"
    legacy_path.write_text(json.dumps([111]), encoding="utf-8")
    store = WhitelistStore(path)
    store.clear()
    store.close()

    store2 = WhitelistStore(path)

    assert store2.list_all() == []


def test_migration_skipped_when_database_already_has_entries(tmp_path: Path) -> None:
    path = tmp_path / "whitelist.db"
    store = WhitelistStore(path)
    store.add(999)
    store.close()
    legacy_path = tmp_path / "whitelist.json"
    legacy_path.write_text(json.dumps([111]), encoding="utf-8")

    store2 = WhitelistStore(path)

    assert store2.list_all() == [999]
    assert legacy_path.exists()


def test_migration_ignores_non_list_top_level(tmp_path: Path) -> None:
    legacy_path = tmp_path / "whitelist.json"
    legacy_path.write_text(json.dumps({"123456789012345678": True}), encoding="utf-8")

    store = WhitelistStore(tmp_path / "whitelist.db")

    assert store.list_all() == []
    assert store.contains(123456789012345678) is False


def test_migration_skips_invalid_entries(tmp_path: Path) -> None:
    legacy_path = tmp_path / "whitelist.json"
    legacy_path.write_text(json.dumps([123, "not-a-number", None, 456]), encoding="utf-8")

    store = WhitelistStore(tmp_path / "whitelist.db")

    assert store.list_all() == [123, 456]
