from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DownloadedMediaFile:
    path: Path


@dataclass(frozen=True, slots=True)
class DownloadedMediaAsset:
    filename: str
    data: bytes
