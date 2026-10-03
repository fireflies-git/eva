"""Bounded, ephemeral Discord attachment conversion for multimodal prompts."""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass
from typing import Any

import aiohttp
from PIL import Image

from eva.ai.schemas import ContentPart, FilePart, ImagePart, VideoPart
from eva.security.urls import PolicyResolver, URLPolicyError, validate_url_for_request

logger = logging.getLogger(__name__)

MAX_ATTACHMENTS = 8
MAX_TOTAL_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_DIMENSION = 6000

IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/jpg"})
VIDEO_TYPES = frozenset({"video/mp4", "video/mkv", "video/quicktime", "video/x-matroska"})
FILE_TYPES = frozenset(
    {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "text/csv",
        "application/json",
        "application/jsonl",
        "application/rtf",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
)


@dataclass(frozen=True, slots=True)
class AttachmentMarker:
    filename: str
    reason: str

    def text(self) -> str:
        return f"[attachment omitted: {self.filename} ({self.reason})]"


@dataclass(slots=True)
class AttachmentBudget:
    count: int = 0
    total_bytes: int = 0

    def reserve(self, size: int) -> str | None:
        if self.count >= MAX_ATTACHMENTS:
            return "attachment limit"
        if size < 0 or self.total_bytes + size > MAX_TOTAL_BYTES:
            return "request size limit"
        self.count += 1
        self.total_bytes += size
        return None


async def attachment_to_part(
    attachment: Any,
    *,
    budget: AttachmentBudget,
    allow_private_outbound: bool = False,
    allowed_hosts: frozenset[str] | None = None,
    timeout_seconds: float = 15.0,
) -> ContentPart | AttachmentMarker:
    filename = str(getattr(attachment, "filename", "attachment"))[:160]
    content_type = str(getattr(attachment, "content_type", "") or "").lower().split(";", 1)[0]
    size = _attachment_size(attachment)
    if content_type not in IMAGE_TYPES | VIDEO_TYPES | FILE_TYPES:
        return AttachmentMarker(filename, "unsupported type")

    limit = MAX_IMAGE_BYTES if content_type in IMAGE_TYPES else MAX_FILE_BYTES
    if size is not None and size > limit:
        return AttachmentMarker(filename, "size limit")
    if size is None:
        size = limit
    reason = budget.reserve(size)
    if reason is not None:
        return AttachmentMarker(filename, reason)

    url = getattr(attachment, "url", None)
    if not isinstance(url, str) or not url.strip():
        return AttachmentMarker(filename, "missing URL")
    try:
        await validate_url_for_request(
            url,
            allow_private=allow_private_outbound,
            allowed_hosts=allowed_hosts,
        )
    except URLPolicyError:
        return AttachmentMarker(filename, "URL blocked")

    if content_type in VIDEO_TYPES:
        return VideoPart(type="video_url", video_url={"url": url})

    try:
        data = await _download_bytes(
            url,
            max_bytes=limit,
            allow_private_outbound=allow_private_outbound,
            allowed_hosts=allowed_hosts,
            timeout_seconds=timeout_seconds,
        )
    except (AIClientMediaError, aiohttp.ClientError, TimeoutError):
        return AttachmentMarker(filename, "download failed")

    if content_type in IMAGE_TYPES:
        dimensions = _read_image_dimensions(data, content_type=content_type)
        if dimensions is None:
            return AttachmentMarker(filename, "invalid image")
        width, height = dimensions
        if max(width, height) > MAX_IMAGE_DIMENSION:
            return AttachmentMarker(filename, "image dimensions")
        return ImagePart(
            type="image_url",
            image_url={"url": _data_url(content_type, data)},
        )

    return FilePart(
        type="file",
        file={"file_data": _data_url(content_type, data), "filename": filename},
    )


class AIClientMediaError(RuntimeError):
    pass


async def _download_bytes(
    url: str,
    *,
    max_bytes: int,
    allow_private_outbound: bool,
    allowed_hosts: frozenset[str] | None,
    timeout_seconds: float,
) -> bytes:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(
        timeout=timeout,
        connector=aiohttp.TCPConnector(
            resolver=PolicyResolver(allow_private=allow_private_outbound),
            use_dns_cache=False,
        ),
    ) as session:
        async with session.get(url, allow_redirects=False) as response:
            if response.status != 200:
                raise AIClientMediaError("attachment request failed")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.content.iter_chunked(64 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise AIClientMediaError("attachment exceeds size limit")
                chunks.append(chunk)
            return b"".join(chunks)


def _attachment_size(attachment: Any) -> int | None:
    size = getattr(attachment, "size", None)
    return size if isinstance(size, int) and size >= 0 else None


def _read_image_dimensions(data: bytes, *, content_type: str) -> tuple[int, int] | None:
    try:
        with Image.open(io.BytesIO(data)) as image:
            expected_format = "PNG" if content_type == "image/png" else "JPEG"
            if image.format != expected_format:
                return None
            return image.size
    except Exception:
        return None


def _data_url(content_type: str, data: bytes) -> str:
    return f"data:{content_type};base64,{base64.b64encode(data).decode('ascii')}"


__all__ = [
    "AttachmentBudget",
    "AttachmentMarker",
    "MAX_ATTACHMENTS",
    "MAX_TOTAL_BYTES",
    "attachment_to_part",
]
