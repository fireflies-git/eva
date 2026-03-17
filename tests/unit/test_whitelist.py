import json
from pathlib import Path

from eva.state.whitelist import WhitelistStore


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
