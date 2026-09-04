from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from eva.yuri import YuriDatabaseError, YuriImageService


def _create_database(path: Path, rows: list[tuple[bytes, int]]) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            "CREATE TABLE posts (id INTEGER PRIMARY KEY, permalink TEXT, image BLOB, nsfw BOOL)"
        )
        database.executemany(
            "INSERT INTO posts (permalink, image, nsfw) VALUES (?, ?, ?)",
            [(f"/post/{index}", image, nsfw) for index, (image, nsfw) in enumerate(rows, 1)],
        )


def test_yuri_service_returns_a_random_image_and_preserves_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "yuri.db"
    _create_database(
        database_path,
        [
            (b"not selected", 0),
            (b"\x89PNG\r\n\x1a\nimage", 1),
        ],
    )
    service = YuriImageService(db_path=database_path, random_index=lambda count: count - 1)

    asset = asyncio.run(service.get_random_image(allow_nsfw=True))

    assert asset.image_id == 2
    assert asset.filename == "yuri-2.png"
    assert asset.data == b"\x89PNG\r\n\x1a\nimage"
    assert asset.permalink == "/post/2"
    assert asset.is_nsfw is True


def test_yuri_service_rejects_missing_database(tmp_path: Path) -> None:
    service = YuriImageService(db_path=tmp_path / "missing.db")

    with pytest.raises(YuriDatabaseError, match="not available"):
        asyncio.run(service.get_random_image())


def test_yuri_service_rejects_empty_database(tmp_path: Path) -> None:
    database_path = tmp_path / "yuri.db"
    _create_database(database_path, [])
    service = YuriImageService(db_path=database_path)

    with pytest.raises(YuriDatabaseError, match="contains no .*images"):
        asyncio.run(service.get_random_image())


def test_yuri_service_rejects_unsupported_image_data(tmp_path: Path) -> None:
    database_path = tmp_path / "yuri.db"
    _create_database(database_path, [(b"not an image", 0)])
    service = YuriImageService(db_path=database_path, random_index=lambda count: 0)

    with pytest.raises(YuriDatabaseError, match="unsupported image"):
        asyncio.run(service.get_random_image())


def test_yuri_service_limits_random_selection_to_uploadable_images(tmp_path: Path) -> None:
    database_path = tmp_path / "yuri.db"
    _create_database(
        database_path,
        [
            (b"\x89PNG\r\n\x1a\n" + b"large" * 10, 0),
            (b"\x89PNG\r\n\x1a\nsmall", 0),
        ],
    )
    service = YuriImageService(db_path=database_path, random_index=lambda count: count - 1)

    asset = asyncio.run(service.get_random_image(max_bytes=15))

    assert asset.image_id == 2


def test_yuri_service_reports_when_upload_limit_excludes_every_image(tmp_path: Path) -> None:
    database_path = tmp_path / "yuri.db"
    _create_database(database_path, [(b"\x89PNG\r\n\x1a\nimage", 0)])
    service = YuriImageService(db_path=database_path)

    with pytest.raises(YuriDatabaseError, match="small enough"):
        asyncio.run(service.get_random_image(max_bytes=1))


def test_yuri_service_excludes_nsfw_images_when_not_allowed(tmp_path: Path) -> None:
    database_path = tmp_path / "yuri.db"
    _create_database(
        database_path,
        [
            (b"\x89PNG\r\n\x1a\nnsfw", 1),
            (b"\x89PNG\r\n\x1a\nsfw", 0),
        ],
    )
    service = YuriImageService(db_path=database_path, random_index=lambda count: 0)

    asset = asyncio.run(service.get_random_image(allow_nsfw=False))

    assert asset.image_id == 2
    assert asset.is_nsfw is False
