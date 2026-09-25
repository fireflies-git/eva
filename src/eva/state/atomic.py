"""Atomic text writes for persistent state files."""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path

from eva.runtime import validate_secure_path


def validate_state_path(path: Path) -> Path:
    """Validate a persistent state file before reading or writing it."""

    return validate_secure_path(path)


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + same-volume replace).

    A crash mid-write then damages only the temp file, never the live state
    file. ``os.replace`` is atomic for same-volume renames on Windows/POSIX.
    """
    path = validate_state_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp-",
        dir=path.parent,
        text=True,
    )
    tmp_path = Path(temp_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temp_file:
            temp_file.write(text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        if os.name != "nt":
            tmp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)
