from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

import discord

from eva.ai.schemas import VisionImage
from eva.constants import MAX_VISION_IMAGE_BYTES, MAX_VISION_IMAGES_PER_MESSAGE
from eva.discord.triggers import is_vision_request
from eva.state.vision_images import VisionImageStore

logger = logging.getLogger(__name__)

_SUPPORTED_MIME_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
    }
)
_SUPPORTED_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png", ".gif", ".webp"})
_CLEARLY_NON_IMAGE_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "application/zip",
        "audio/mpeg",
        "audio/ogg",
        "text/plain",
        "video/mp4",
        "video/webm",
    }
)
_CLEARLY_NON_IMAGE_EXTENSIONS = frozenset(
    {".7z", ".csv", ".doc", ".docx", ".mp3", ".mp4", ".pdf", ".txt", ".zip"}
)


@dataclass(frozen=True, slots=True)
class VisionSelection:
    requested: bool
    images: tuple[VisionImage, ...] = ()


def has_image_like_attachment(message: discord.Message) -> bool:
    return any(_attachment_looks_like_image(attachment) for attachment in _get_attachments(message))


def image_attachment_names(message: discord.Message) -> tuple[str, ...]:
    names: list[str] = []
    for attachment in _get_attachments(message):
        if not _attachment_may_contain_image(attachment):
            continue
        filename = getattr(attachment, "filename", None)
        if isinstance(filename, str) and filename.strip():
            names.append(filename.strip())
        if len(names) >= MAX_VISION_IMAGES_PER_MESSAGE:
            break
    return tuple(names)


async def remember_message_images(
    message: discord.Message,
    *,
    channel_id: int,
    store: VisionImageStore,
) -> None:
    message_id = getattr(message, "id", None)
    if not isinstance(message_id, int):
        return

    images: list[VisionImage] = []
    for attachment in _get_attachments(message):
        if not _attachment_may_contain_image(attachment):
            continue
        if len(images) >= MAX_VISION_IMAGES_PER_MESSAGE:
            break

        declared_size = getattr(attachment, "size", None)
        if isinstance(declared_size, int) and declared_size > MAX_VISION_IMAGE_BYTES:
            logger.warning(
                "Skipping oversized vision attachment filename=%s size=%s",
                getattr(attachment, "filename", "unknown"),
                declared_size,
            )
            continue

        data = await _read_attachment(attachment)
        if data is None:
            continue
        if not data:
            logger.warning(
                "Skipping empty vision attachment filename=%s",
                getattr(attachment, "filename", "unknown"),
            )
            continue
        if len(data) > MAX_VISION_IMAGE_BYTES:
            logger.warning(
                "Skipping oversized vision attachment filename=%s size=%s",
                getattr(attachment, "filename", "unknown"),
                len(data),
            )
            continue

        mime_type = _detect_image_mime_type(data)
        if mime_type is None:
            logger.warning(
                "Skipping unsupported vision attachment filename=%s",
                getattr(attachment, "filename", "unknown"),
            )
            continue

        filename = getattr(attachment, "filename", None)
        images.append(
            VisionImage(
                message_id=message_id,
                filename=filename.strip() if isinstance(filename, str) else "image",
                mime_type=mime_type,
                data=data,
            )
        )

    if images:
        store.put(channel_id, message_id, images)


def resolve_vision_selection(
    message: discord.Message,
    *,
    channel_id: int,
    user_query: str,
    reply_context: str | None,
    store: VisionImageStore,
) -> VisionSelection:
    message_id = getattr(message, "id", None)
    current_images = (
        store.get_for_message(channel_id, message_id) if isinstance(message_id, int) else ()
    )

    reference = getattr(message, "reference", None)
    referenced_message_id = getattr(reference, "message_id", None)
    reply_images = (
        store.get_for_message(channel_id, referenced_message_id)
        if isinstance(referenced_message_id, int)
        else ()
    )
    latest_images = store.get_latest(channel_id)

    current_has_attachments = has_image_like_attachment(message)
    resolved_reference = getattr(reference, "resolved", None)
    resolved_reference_has_image = resolved_reference is not None and has_image_like_attachment(
        cast(discord.Message, resolved_reference)
    )
    reply_has_attachments = (
        _reply_context_has_attachments(reply_context) or resolved_reference_has_image
    )
    has_image_context = bool(
        current_images
        or reply_images
        or latest_images
        or current_has_attachments
        or reply_has_attachments
    )
    requested = is_vision_request(user_query, has_image_context=has_image_context)
    if not requested:
        return VisionSelection(requested=False)

    if current_images:
        return VisionSelection(requested=True, images=current_images)
    if current_has_attachments:
        return VisionSelection(requested=True)
    if reply_images:
        return VisionSelection(requested=True, images=reply_images)
    if reply_has_attachments:
        return VisionSelection(requested=True)
    return VisionSelection(requested=True, images=latest_images)


def _get_attachments(message: discord.Message) -> list[object]:
    raw_attachments = getattr(message, "attachments", None)
    if raw_attachments is None:
        return []
    try:
        return list(raw_attachments)
    except TypeError:
        return []


def _attachment_looks_like_image(attachment: object) -> bool:
    content_type = getattr(attachment, "content_type", None)
    if isinstance(content_type, str):
        normalized_content_type = content_type.split(";", 1)[0].strip().lower()
        if normalized_content_type in _SUPPORTED_MIME_TYPES:
            return True

    filename = getattr(attachment, "filename", None)
    if not isinstance(filename, str):
        return False
    lowered_filename = filename.lower()
    return any(lowered_filename.endswith(extension) for extension in _SUPPORTED_EXTENSIONS)


def _attachment_may_contain_image(attachment: object) -> bool:
    if _attachment_looks_like_image(attachment):
        return True

    content_type = getattr(attachment, "content_type", None)
    normalized_content_type = (
        content_type.split(";", 1)[0].strip().lower() if isinstance(content_type, str) else None
    )
    filename = getattr(attachment, "filename", None)
    lowered_filename = filename.lower() if isinstance(filename, str) else None
    filename_is_clearly_non_image = lowered_filename is not None and any(
        lowered_filename.endswith(extension) for extension in _CLEARLY_NON_IMAGE_EXTENSIONS
    )
    mime_is_clearly_non_image = normalized_content_type in _CLEARLY_NON_IMAGE_MIME_TYPES

    # Metadata is only a hint. Read unknown or conflicting attachments so the
    # byte signature, rather than the filename or MIME declaration, decides.
    return not (filename_is_clearly_non_image and mime_is_clearly_non_image)


async def _read_attachment(attachment: object) -> bytes | None:
    read = getattr(attachment, "read", None)
    if not callable(read):
        logger.warning(
            "Skipping vision attachment without a readable payload filename=%s",
            getattr(attachment, "filename", "unknown"),
        )
        return None

    read_callable = cast(Callable[[], Awaitable[object]], read)
    try:
        data = await read_callable()
    except Exception:
        logger.exception(
            "Failed reading vision attachment filename=%s",
            getattr(attachment, "filename", "unknown"),
        )
        return None
    if not isinstance(data, bytes):
        logger.warning(
            "Skipping vision attachment with invalid payload filename=%s",
            getattr(attachment, "filename", "unknown"),
        )
        return None
    return data


def _detect_image_mime_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _reply_context_has_attachments(reply_context: str | None) -> bool:
    if not reply_context:
        return False
    normalized_context = reply_context.lower()
    marker = " | attached:"
    if marker not in normalized_context:
        return False
    attachment_names = normalized_context.split(marker, 1)[1].split("|", 1)[0].split(",")
    return any(
        any(name.strip().endswith(extension) for extension in _SUPPORTED_EXTENSIONS)
        for name in attachment_names
    )
