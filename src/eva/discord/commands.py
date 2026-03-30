from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

import discord

from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.state import WhitelistStore

_MENTION_RE = re.compile(r"<@!?(\d+)>")
ALLOWED_ADMIN_IDS = {213766338005434370, 218675193592283137, 1202356249975595068}

ReplyOrEdit = Callable[[discord.Message, bool, str], Awaitable[None]]


def is_admin_user(*, user_id: int, is_owner: bool) -> bool:
    return is_owner or user_id in ALLOWED_ADMIN_IDS


def list_effective_whitelist(whitelist: WhitelistStore) -> list[int]:
    return sorted(set(whitelist.list_all()) | ALLOWED_ADMIN_IDS)


def _parse_whitelist_query(*, content: str, trigger_prefix: str) -> str | None:
    lowered = content.strip().lower()
    prefix = trigger_prefix.lower()
    if not lowered.startswith(prefix):
        return None

    query = lowered[len(prefix) :].strip()
    if not query.startswith("whitelist"):
        return None
    return query


async def _reply_usage(
    *,
    message: discord.Message,
    is_owner: bool,
    trigger_prefix: str,
    reply_or_edit: ReplyOrEdit,
) -> None:
    usage = f"{trigger_prefix.strip()} whitelist <add|remove|list>"
    await reply_or_edit(message, is_owner, f"{X_MARK} Usage: `{usage}`")


async def _handle_list_command(
    *,
    message: discord.Message,
    is_owner: bool,
    whitelist: WhitelistStore,
    reply_or_edit: ReplyOrEdit,
) -> None:
    ids = list_effective_whitelist(whitelist)
    if not ids:
        await reply_or_edit(message, is_owner, f"{CHECK_MARK} Whitelist is empty.")
        return

    formatted = ", ".join(f"<@{uid}>" for uid in ids)
    await reply_or_edit(message, is_owner, f"{CHECK_MARK} Whitelisted: {formatted}")


def _parse_target_id(*, content: str, parts: list[str]) -> int | None:
    mention_match = _MENTION_RE.search(content)
    if mention_match is not None:
        return int(mention_match.group(1))
    if len(parts) >= 3 and parts[2].isdigit():
        return int(parts[2])
    return None


async def _reply_target_usage(
    *,
    message: discord.Message,
    is_owner: bool,
    trigger_prefix: str,
    subcommand: str,
    reply_or_edit: ReplyOrEdit,
) -> None:
    usage = f"{trigger_prefix.strip()} whitelist {subcommand} @user"
    await reply_or_edit(
        message,
        is_owner,
        f"{X_MARK} Mention a user or provide an ID: `{usage}`",
    )


async def _handle_add_command(
    *,
    message: discord.Message,
    is_owner: bool,
    target_id: int,
    whitelist: WhitelistStore,
    reply_or_edit: ReplyOrEdit,
) -> None:
    if target_id in ALLOWED_ADMIN_IDS:
        await reply_or_edit(
            message,
            is_owner,
            f"{WARNING_MARK} <@{target_id}> is already allowed as an admin.",
        )
        return

    added = whitelist.add(target_id)
    if added:
        await reply_or_edit(message, is_owner, f"{CHECK_MARK} <@{target_id}> added to whitelist.")
        return

    await reply_or_edit(
        message,
        is_owner,
        f"{WARNING_MARK} <@{target_id}> is already whitelisted.",
    )


async def _handle_remove_command(
    *,
    message: discord.Message,
    is_owner: bool,
    target_id: int,
    whitelist: WhitelistStore,
    reply_or_edit: ReplyOrEdit,
) -> None:
    if target_id in ALLOWED_ADMIN_IDS:
        await reply_or_edit(
            message,
            is_owner,
            f"{WARNING_MARK} <@{target_id}> is an admin and is always allowed.",
        )
        return

    removed = whitelist.remove(target_id)
    if removed:
        await reply_or_edit(
            message,
            is_owner,
            f"{CHECK_MARK} <@{target_id}> removed from whitelist.",
        )
        return

    await reply_or_edit(
        message,
        is_owner,
        f"{WARNING_MARK} <@{target_id}> is not whitelisted.",
    )


async def handle_whitelist_command(
    *,
    message: discord.Message,
    content: str,
    is_owner: bool,
    trigger_prefix: str,
    whitelist: WhitelistStore,
    reply_or_edit: ReplyOrEdit,
) -> bool:
    query = _parse_whitelist_query(content=content, trigger_prefix=trigger_prefix)
    if query is None:
        return False

    parts = query.split()
    if len(parts) < 2:
        await _reply_usage(
            message=message,
            is_owner=is_owner,
            trigger_prefix=trigger_prefix,
            reply_or_edit=reply_or_edit,
        )
        return True

    subcommand = parts[1].lower()
    if subcommand == "list":
        await _handle_list_command(
            message=message,
            is_owner=is_owner,
            whitelist=whitelist,
            reply_or_edit=reply_or_edit,
        )
        return True

    if subcommand not in {"add", "remove"}:
        await reply_or_edit(message, is_owner, f"{X_MARK} Unknown subcommand: `{subcommand}`")
        return True

    is_admin = is_admin_user(user_id=message.author.id, is_owner=is_owner)
    if not is_admin:
        await reply_or_edit(
            message,
            is_owner,
            f"{X_MARK} You don't have permission to modify the whitelist.",
        )
        return True

    target_id = _parse_target_id(content=content, parts=parts)
    if target_id is None:
        await _reply_target_usage(
            message=message,
            is_owner=is_owner,
            trigger_prefix=trigger_prefix,
            subcommand=subcommand,
            reply_or_edit=reply_or_edit,
        )
        return True

    if subcommand == "add":
        await _handle_add_command(
            message=message,
            is_owner=is_owner,
            target_id=target_id,
            whitelist=whitelist,
            reply_or_edit=reply_or_edit,
        )
        return True

    await _handle_remove_command(
        message=message,
        is_owner=is_owner,
        target_id=target_id,
        whitelist=whitelist,
        reply_or_edit=reply_or_edit,
    )
    return True
