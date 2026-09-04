from __future__ import annotations

import asyncio
import random
import sqlite3
from collections.abc import Callable
from pathlib import Path

from eva.yuri.schemas import YuriImageAsset

_RandomIndex = Callable[[int], int]


class YuriDatabaseError(RuntimeError):
    """Raised when the local Yuri image database cannot provide an image."""


class YuriImageService:
    def __init__(
        self,
        *,
        db_path: Path,
        random_index: _RandomIndex = random.randrange,
    ) -> None:
        self._db_path = db_path
        self._random_index = random_index

    async def get_random_image(
        self,
        *,
        max_bytes: int | None = None,
        allow_nsfw: bool = False,
    ) -> YuriImageAsset:
        return await asyncio.to_thread(
            self._get_random_image_sync,
            max_bytes,
            allow_nsfw,
        )

    def _get_random_image_sync(self, max_bytes: int | None, allow_nsfw: bool) -> YuriImageAsset:
        if not self._db_path.is_file():
            raise YuriDatabaseError("The Yuri image database is not available.")
        if max_bytes is not None and max_bytes <= 0:
            raise YuriDatabaseError("The Discord upload limit is invalid.")

        try:
            with sqlite3.connect(_read_only_uri(self._db_path), uri=True) as database:
                image_count = _count_images(
                    database,
                    max_bytes=max_bytes,
                    allow_nsfw=allow_nsfw,
                )
                if image_count == 0:
                    raise YuriDatabaseError(_no_images_message(max_bytes, allow_nsfw))

                filters = "typeof(image) = 'blob' AND length(image) > 0"
                query_parameters: tuple[int, ...] = (self._random_index(image_count),)
                if max_bytes is not None:
                    filters += " AND length(image) <= ?"
                    query_parameters = (max_bytes, *query_parameters)
                if not allow_nsfw:
                    filters += " AND COALESCE(nsfw, 0) = 0"
                row = database.execute(
                    f"""
                    SELECT id, permalink, image, nsfw
                    FROM posts
                    WHERE {filters}
                    ORDER BY id
                    LIMIT 1 OFFSET ?
                    """,
                    query_parameters,
                ).fetchone()
        except YuriDatabaseError:
            raise
        except sqlite3.Error as exc:
            raise YuriDatabaseError("The Yuri image database could not be read.") from exc

        if row is None:
            raise YuriDatabaseError("The Yuri image database returned no image.")

        image_id, permalink, image, nsfw = row
        if not isinstance(image_id, int) or not isinstance(image, bytes):
            raise YuriDatabaseError("The Yuri image database contains a malformed image row.")

        extension = _detect_image_extension(image)
        if extension is None:
            raise YuriDatabaseError("The Yuri image database contains an unsupported image.")

        normalized_permalink = permalink if isinstance(permalink, str) else None
        return YuriImageAsset(
            image_id=image_id,
            filename=f"yuri-{image_id}{extension}",
            data=image,
            permalink=normalized_permalink,
            is_nsfw=bool(nsfw),
        )


def _read_only_uri(path: Path) -> str:
    return f"{path.resolve().as_uri()}?mode=ro"


def _count_images(
    database: sqlite3.Connection,
    *,
    max_bytes: int | None,
    allow_nsfw: bool,
) -> int:
    query = "SELECT COUNT(*) FROM posts WHERE typeof(image) = 'blob' AND length(image) > 0"
    parameters: tuple[int, ...] = ()
    if max_bytes is not None:
        query += " AND length(image) <= ?"
        parameters = (max_bytes,)
    if not allow_nsfw:
        query += " AND COALESCE(nsfw, 0) = 0"
    row = database.execute(query, parameters).fetchone()
    if row is None or not isinstance(row[0], int):
        raise YuriDatabaseError("The Yuri image database returned an invalid image count.")
    return row[0]


def _no_images_message(max_bytes: int | None, allow_nsfw: bool) -> str:
    scope = "images" if allow_nsfw else "SFW images"
    if max_bytes is None:
        return f"The Yuri image database contains no {scope}."
    return f"The Yuri image database has no {scope} small enough to upload."


def _detect_image_extension(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    return None
