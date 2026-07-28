"""Atomic text writes for persistent state files."""

from __future__ import annotations

import os
from pathlib import Path


def write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` atomically (temp file + same-volume replace).

    A crash mid-write then damages only the temp file, never the live state
    file. ``os.replace`` is atomic for same-volume renames on Windows/POSIX.
    """
    tmp_path = path.with_name(f"{path.name}.tmp")
    tmp_path.write_text(text, encoding="utf-8")
    os.replace(tmp_path, path)
