from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GeneratedImage:
    url: str
    thumbnail_url: str | None = None
    download_url: str | None = None
    mime_type: str | None = None
    source: str | None = None
    generation_model: str | None = None
    prompt: str | None = None


@dataclass(frozen=True, slots=True)
class GeneratedImageAsset:
    filename: str
    data: bytes
    mime_type: str | None = None


@dataclass(frozen=True, slots=True)
class ImageResultBundle:
    id: str = ""
    model: str = ""
    prompt: str = ""
    images: list[GeneratedImage] = field(default_factory=list)
    assets: list[GeneratedImageAsset] = field(default_factory=list)
    answer: str = ""
    is_error: bool = False

    @classmethod
    def error(cls) -> ImageResultBundle:
        return cls(is_error=True)
