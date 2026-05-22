import json
from pathlib import Path

import pytest

from eva.state.tracked_messages import TrackedMessageStore


def test_add_and_contains(tmp_path: Path) -> None:
    store = TrackedMessageStore(path=tmp_path / "tracked.json")
    assert store.contains(1) is False
    store.add(1)
    assert store.contains(1) is True


def test_evicts_oldest_when_over_capacity(tmp_path: Path) -> None:
    store = TrackedMessageStore(path=tmp_path / "tracked.json", max_size=3)
    store.add(1)
    store.add(2)
    store.add(3)
    store.add(4)

    assert store.contains(1) is False
    assert store.contains(2) is True
    assert store.contains(3) is True
    assert store.contains(4) is True


def test_readding_existing_id_refreshes_recency(tmp_path: Path) -> None:
    store = TrackedMessageStore(path=tmp_path / "tracked.json", max_size=3)
    store.add(1)
    store.add(2)
    store.add(3)
    store.add(1)
    store.add(4)

    assert store.contains(1) is True
    assert store.contains(2) is False
    assert store.contains(3) is True
    assert store.contains(4) is True


def test_invalid_max_size_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        TrackedMessageStore(path=tmp_path / "tracked.json", max_size=0)
    with pytest.raises(ValueError):
        TrackedMessageStore(path=tmp_path / "tracked.json", max_size=-1)


def test_persists_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "tracked.json"
    store = TrackedMessageStore(path=path)
    store.add(111)
    store.add(222)

    reopened = TrackedMessageStore(path=path)
    assert reopened.contains(111) is True
    assert reopened.contains(222) is True


def test_persistence_file_format(tmp_path: Path) -> None:
    path = tmp_path / "tracked.json"
    store = TrackedMessageStore(path=path)
    store.add(42)
    store.add(43)
    assert json.loads(path.read_text(encoding="utf-8")) == [42, 43]


def test_load_tolerates_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "tracked.json"
    path.write_text("not json", encoding="utf-8")
    store = TrackedMessageStore(path=path)
    assert store.contains(1) is False
    store.add(1)
    assert store.contains(1) is True


def test_load_tolerates_non_list_payload(tmp_path: Path) -> None:
    path = tmp_path / "tracked.json"
    path.write_text(json.dumps({"oops": 1}), encoding="utf-8")
    store = TrackedMessageStore(path=path)
    assert store.contains(1) is False


def test_load_truncates_to_max_size(tmp_path: Path) -> None:
    path = tmp_path / "tracked.json"
    path.write_text(json.dumps([1, 2, 3, 4, 5]), encoding="utf-8")
    store = TrackedMessageStore(path=path, max_size=3)
    # Most recent IDs win since the on-disk order is oldest -> newest.
    assert store.contains(1) is False
    assert store.contains(2) is False
    assert store.contains(3) is True
    assert store.contains(4) is True
    assert store.contains(5) is True


def test_persistence_disabled_when_path_is_none(tmp_path: Path) -> None:
    store = TrackedMessageStore(path=None)
    store.add(1)
    assert store.contains(1) is True
    # Ensure no incidental files were written next to the test directory.
    assert list(tmp_path.iterdir()) == []
