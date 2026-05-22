from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import discord

from eva.constants import CHECK_MARK, X_MARK
from eva.discord.command_outcome import CommandOutcome
from eva.discord.commands import is_admin_user
from eva.downloads import DownloadClientError, DownloadService
from eva.state import WhitelistStore

_DOWNLOAD_COMMANDS = ("dl", "download")


async def handle_download_command(
    *,
    message: discord.Message,
    content: str,
    is_owner: bool,
    trigger_prefix: str,
    whitelist: WhitelistStore,
    download_service: DownloadService | None,
) -> CommandOutcome:
    url = _parse_download_query(content=content, trigger_prefix=trigger_prefix)
    if url is None:
        return CommandOutcome.not_handled()

    is_allowed = is_admin_user(user_id=message.author.id, is_owner=is_owner) or whitelist.contains(
        message.author.id
    )
    if not is_allowed:
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} You don't have permission to use download commands.",
        )

    if download_service is None:
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} Download access is disabled.",
        )

    if not url:
        usage = f"{trigger_prefix.strip()} dl <url>"
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} Usage: `{usage}`",
        )

    guild_filesize_limit = _get_guild_filesize_limit(message)
    async with _typing_context(message.channel):
        try:
            asset = await download_service.download_media(
                url=url,
                guild_filesize_limit=guild_filesize_limit,
            )
        except DownloadClientError as exc:
            return CommandOutcome(
                handled=True,
                content=f"{X_MARK} {exc}",
            )

    return CommandOutcome(
        handled=True,
        content=f"{CHECK_MARK} Downloaded `{asset.filename}`",
        attachments=[(asset.filename, asset.data)],
    )


def _parse_download_query(*, content: str, trigger_prefix: str) -> str | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None

    remainder = text[len(prefix) :].lstrip()
    lowered = remainder.lower()
    for command in _DOWNLOAD_COMMANDS:
        if lowered == command:
            return ""
        if lowered.startswith(f"{command} "):
            return remainder[len(command) :].strip()
    return None


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
