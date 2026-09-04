from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class YuriImageAsset:
    image_id: int
    filename: str
    data: bytes
    permalink: str | None
    is_nsfw: bool
