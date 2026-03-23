from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

import discord

from eva.discord.formatting import build_plain_response_chunks, build_response_chunks

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    primary_delivered: bool
    tracked_message_ids: list[int] = field(default_factory=list)
    had_continuation_failures: bool = False


def _build_files(attachments: list[tuple[str, bytes]]) -> list[discord.File]:
    files: list[discord.File] = []
    for filename, data in attachments:
        files.append(discord.File(fp=io.BytesIO(data), filename=filename))
    return files


async def safe_edit(
    message: discord.Message,
    content: str,
    *,
    attachments: list[tuple[str, bytes]] | None = None,
) -> bool:
    try:
        if attachments:
            files = _build_files(attachments)
            await message.edit(content=content, suppress=True, attachments=files)
        else:
            await message.edit(content=content, suppress=True)
        return True
    except Exception:
        logger.exception("Failed to edit message")
        return False


async def safe_send(
    channel: discord.abc.Messageable,
    content: str,
    *,
    attachments: list[tuple[str, bytes]] | None = None,
) -> discord.Message | None:
    send = getattr(channel, "send", None)
    if send is None:
        return None
    try:
        if attachments:
            files = _build_files(attachments)
            return await send(content=content, files=files, suppress_embeds=True)
        return await send(content=content, suppress_embeds=True)
    except Exception:
        logger.exception("Failed to send continuation message")
        return None


async def safe_reply(
    message: discord.Message,
    content: str,
    *,
    attachments: list[tuple[str, bytes]] | None = None,
) -> discord.Message | None:
    try:
        if attachments:
            files = _build_files(attachments)
            return await message.reply(content=content, files=files, suppress_embeds=True)
        return await message.reply(content=content, suppress_embeds=True)
    except Exception:
        logger.exception("Failed to reply to message")
        return None


async def safe_reply_or_edit(message: discord.Message, is_owner: bool, content: str) -> None:
    if is_owner:
        await safe_edit(message, content)
    else:
        await safe_reply(message, content)


async def deliver_owner_response(
    *,
    message: discord.Message,
    original_content: str,
    reply_content: str,
    reply_attachments: list[tuple[str, bytes]] | None = None,
) -> DeliveryResult:
    response_chunks = build_response_chunks(original_content, reply_content)
    primary_delivered = await safe_edit(
        message,
        response_chunks[0],
        attachments=reply_attachments,
    )
    if not primary_delivered:
        return DeliveryResult(primary_delivered=False)

    tracked_message_ids = [message.id]
    had_continuation_failures = False
    for continuation in response_chunks[1:]:
        sent_message = await safe_send(message.channel, continuation)
        if sent_message is None:
            had_continuation_failures = True
            continue
        tracked_message_ids.append(sent_message.id)

    return DeliveryResult(
        primary_delivered=True,
        tracked_message_ids=tracked_message_ids,
        had_continuation_failures=had_continuation_failures,
    )


async def deliver_reply_response(
    *,
    message: discord.Message,
    reply_content: str,
    reply_attachments: list[tuple[str, bytes]] | None = None,
) -> DeliveryResult:
    chunks = build_plain_response_chunks(reply_content)
    first = await safe_reply(message, chunks[0], attachments=reply_attachments)
    if first is None:
        return DeliveryResult(primary_delivered=False)

    tracked_message_ids = [first.id]
    had_continuation_failures = False
    for continuation in chunks[1:]:
        sent_message = await safe_send(message.channel, continuation)
        if sent_message is None:
            had_continuation_failures = True
            continue
        tracked_message_ids.append(sent_message.id)

    return DeliveryResult(
        primary_delivered=True,
        tracked_message_ids=tracked_message_ids,
        had_continuation_failures=had_continuation_failures,
    )
