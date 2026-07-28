import json
from pathlib import Path

from eva.state.atomic import write_text_atomic


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
