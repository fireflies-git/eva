from __future__ import annotations

import asyncio
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, cast

import discord

from eva.discord.formatting import build_plain_response_chunks, build_response_chunks

logger = logging.getLogger(__name__)


class ApplicationGroupChannel(Protocol):
    recipients: list[discord.abc.Snowflake]

    async def remove_recipients(self, *recipients: discord.abc.Snowflake) -> None: ...

    async def leave(self, *, silent: bool = False) -> None: ...


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    primary_delivered: bool
    tracked_message_ids: list[int] = field(default_factory=list)
    had_continuation_failures: bool = False


def _build_files(
    attachments: list[tuple[str, bytes]],
    *,
    spoiler: bool = False,
) -> list[discord.File]:
    files: list[discord.File] = []
    for filename, data in attachments:
        files.append(discord.File(fp=io.BytesIO(data), filename=filename, spoiler=spoiler))
    return files


async def safe_edit(
    message: discord.Message,
    content: str,
    *,
    attachments: list[tuple[str, bytes]] | None = None,
    suppress_embeds: bool = True,
    spoiler_attachments: bool = False,
) -> bool:
    try:
        if attachments:
            files = _build_files(attachments, spoiler=spoiler_attachments)
            await message.edit(
                content=content, suppress=suppress_embeds, attachments=files
            )
        else:
            await message.edit(content=content, suppress=suppress_embeds)
        return True
    except Exception:
        logger.exception("Failed to edit message")
        return False


async def safe_send(
    channel: discord.abc.Messageable,
    content: str,
    *,
    attachments: list[tuple[str, bytes]] | None = None,
    suppress_embeds: bool = True,
    spoiler_attachments: bool = False,
) -> discord.Message | None:
    send = getattr(channel, "send", None)
    if send is None:
        return None
    try:
        if attachments:
            files = _build_files(attachments, spoiler=spoiler_attachments)
            return await send(content=content, files=files, suppress_embeds=suppress_embeds)
        return await send(content=content, suppress_embeds=suppress_embeds)
    except Exception:
        logger.exception("Failed to send continuation message")
        return None


async def safe_reply(
    message: discord.Message,
    content: str,
    *,
    attachments: list[tuple[str, bytes]] | None = None,
    suppress_embeds: bool = True,
    spoiler_attachments: bool = False,
) -> discord.Message | None:
    try:
        if attachments:
            files = _build_files(attachments, spoiler=spoiler_attachments)
            return await message.reply(
                content=content, files=files, suppress_embeds=suppress_embeds
            )
        return await message.reply(content=content, suppress_embeds=suppress_embeds)
    except Exception:
        logger.exception("Failed to reply to message")
        return None


async def safe_reply_or_edit(message: discord.Message, is_owner: bool, content: str) -> None:
    if is_owner:
        await safe_edit(message, content)
    else:
        await safe_reply(message, content)


async def close_application_group(channel: discord.abc.Messageable) -> None:
    """Remove application participants and leave the now-closed group."""
    if not hasattr(channel, "remove_recipients"):
        logger.warning("Application channel does not support removing participants")
    else:
        group = cast(ApplicationGroupChannel, channel)
        for recipient in tuple(group.recipients):
            try:
                await group.remove_recipients(recipient)
            except Exception:
                logger.exception(
                    "Failed to remove application participant %s",
                    getattr(recipient, "id", "unknown"),
                )

    if not hasattr(channel, "leave"):
        logger.warning("Application channel does not support leaving")
        return
    try:
        await cast(ApplicationGroupChannel, channel).leave(silent=True)
    except Exception:
        logger.exception("Failed to leave application group")


async def wait_before_followup(
    channel: discord.abc.Messageable,
    *,
    content: str,
    delay_seconds: Callable[[str], float],
) -> None:
    """Show typing while waiting before sending a split follow-up message."""
    delay = max(delay_seconds(content), 0.0)
    typing = getattr(channel, "typing", None)
    if typing is None:
        if delay:
            await asyncio.sleep(delay)
        return

    try:
        async with typing():
            if delay:
                await asyncio.sleep(delay)
    except Exception:
        logger.exception("Failed to show typing indicator before follow-up")
        if delay:
            await asyncio.sleep(delay)


async def deliver_owner_response(
    *,
    message: discord.Message,
    original_content: str,
    reply_content: str,
    reply_attachments: list[tuple[str, bytes]] | None = None,
    suppress_embeds: bool = True,
    spoiler_attachments: bool = False,
    followup_delay_seconds: Callable[[str], float] | None = None,
) -> DeliveryResult:
    response_chunks = build_response_chunks(original_content, reply_content)
    primary_delivered = await safe_edit(
        message,
        response_chunks[0],
        attachments=reply_attachments,
        suppress_embeds=suppress_embeds,
        spoiler_attachments=spoiler_attachments,
    )
    if not primary_delivered:
        return DeliveryResult(primary_delivered=False)

    tracked_message_ids = [message.id]
    had_continuation_failures = False
    for continuation in response_chunks[1:]:
        if followup_delay_seconds is not None:
            await wait_before_followup(
                message.channel,
                content=continuation,
                delay_seconds=followup_delay_seconds,
            )
        sent_message = await safe_send(
            message.channel, continuation, suppress_embeds=suppress_embeds
        )
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
    suppress_embeds: bool = True,
    spoiler_attachments: bool = False,
    followup_delay_seconds: Callable[[str], float] | None = None,
) -> DeliveryResult:
    chunks = build_plain_response_chunks(reply_content)
    first = await safe_reply(
        message,
        chunks[0],
        attachments=reply_attachments,
        suppress_embeds=suppress_embeds,
        spoiler_attachments=spoiler_attachments,
    )
    if first is None:
        return DeliveryResult(primary_delivered=False)

    tracked_message_ids = [first.id]
    had_continuation_failures = False
    for continuation in chunks[1:]:
        if followup_delay_seconds is not None:
            await wait_before_followup(
                message.channel,
                content=continuation,
                delay_seconds=followup_delay_seconds,
            )
        sent_message = await safe_send(
            message.channel, continuation, suppress_embeds=suppress_embeds
        )
        if sent_message is None:
            had_continuation_failures = True
            continue
        tracked_message_ids.append(sent_message.id)

    return DeliveryResult(
        primary_delivered=True,
        tracked_message_ids=tracked_message_ids,
        had_continuation_failures=had_continuation_failures,
    )
