from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

import discord

from eva.constants import CHECK_MARK, DEFAULT_DM_DOWNLOAD_LIMIT_BYTES, WARNING_MARK, X_MARK
from eva.discord.command_outcome import CommandOutcome
from eva.yuri import YuriDatabaseError, YuriImageAsset

logger = logging.getLogger(__name__)


class YuriImageProvider(Protocol):
    async def get_random_image(
        self,
        *,
        max_bytes: int,
        allow_nsfw: bool,
    ) -> YuriImageAsset: ...


async def handle_yuri_command(
    *,
    message: discord.Message,
    content: str,
    trigger_prefix: str,
    yuri_service: YuriImageProvider | None,
) -> CommandOutcome:
    if not is_yuri_command(content=content, trigger_prefix=trigger_prefix):
        return CommandOutcome.not_handled()

    if yuri_service is None:
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} Yuri images are disabled.",
        )

    allow_nsfw = _is_private_channel(message)
    max_bytes = _get_guild_filesize_limit(message) or DEFAULT_DM_DOWNLOAD_LIMIT_BYTES
    async with _typing_context(message.channel):
        try:
            asset = await yuri_service.get_random_image(
                max_bytes=max_bytes,
                allow_nsfw=allow_nsfw,
            )
        except YuriDatabaseError as exc:
            logger.warning("Yuri command could not load an image: %s", exc)
            return CommandOutcome(
                handled=True,
                content=f"{X_MARK} {exc}",
            )

    if asset.is_nsfw and not allow_nsfw:
        logger.error("Yuri service returned an NSFW image for a server channel")
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} NSFW Yuri images are unavailable in server channels.",
        )

    if asset.is_nsfw:
        content = f"{WARNING_MARK} Marked NSFW — `{asset.filename}`"
    else:
        content = f"{CHECK_MARK} `{asset.filename}`"
    return CommandOutcome(
        handled=True,
        content=content,
        attachments=[(asset.filename, asset.data)],
        spoiler_attachments=asset.is_nsfw,
    )


def is_yuri_command(*, content: str, trigger_prefix: str) -> bool:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return False
    return text[len(prefix) :].strip().lower() == "yuri"


def _is_private_channel(message: discord.Message) -> bool:
    # Direct messages and group DMs both have no guild; server channels do.
    return getattr(message, "guild", None) is None


def _get_guild_filesize_limit(message: discord.Message) -> int | None:
    guild = getattr(message, "guild", None)
    limit = getattr(guild, "filesize_limit", None)
    return limit if isinstance(limit, int) and limit > 0 else None


@asynccontextmanager
async def _typing_context(channel: discord.abc.Messageable) -> AsyncIterator[None]:
    typing = getattr(channel, "typing", None)
    if typing is None:
        yield
        return

    async with typing():
        yield
