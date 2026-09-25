import json
from pathlib import Path

import pytest

from eva.runtime import UnsafePathError
from eva.state.atomic import write_text_atomic
from eva.state.user_memory import UserMemoryStore
from eva.state.whitelist import WhitelistStore


def test_write_text_atomic_writes_content_without_tmp_leftovers(tmp_path: Path) -> None:
    path = tmp_path / "state.json"

    write_text_atomic(path, json.dumps({"a": 1}) + "\n")

    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
    assert not (tmp_path / "state.json.tmp").exists()


def test_write_text_atomic_replaces_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text("old", encoding="utf-8")

    write_text_atomic(path, "new")

    assert path.read_text(encoding="utf-8") == "new"


def test_persistent_state_stores_reject_symlinked_files(tmp_path: Path) -> None:
    target = tmp_path / "outside-state.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "user_memory.json"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(UnsafePathError):
        UserMemoryStore(path=link)
    with pytest.raises(UnsafePathError):
        write_text_atomic(link, "{}\n")


def test_whitelist_store_rejects_symlinked_database(tmp_path: Path) -> None:
    target = tmp_path / "outside-whitelist.db"
    target.touch()
    link = tmp_path / "whitelist.db"
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    with pytest.raises(UnsafePathError):
        WhitelistStore(link)
