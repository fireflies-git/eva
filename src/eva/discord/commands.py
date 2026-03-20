from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

import discord

from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.state import WhitelistStore

_MENTION_RE = re.compile(r"<@!?(\d+)>")
ALLOWED_ADMIN_IDS = {213766338005434370, 218675193592283137}

ReplyOrEdit = Callable[[discord.Message, bool, str], Awaitable[None]]


async def handle_whitelist_command(
    *,
    message: discord.Message,
    content: str,
    is_owner: bool,
    trigger_prefix: str,
    whitelist: WhitelistStore,
    reply_or_edit: ReplyOrEdit,
) -> bool:
    lowered = content.strip().lower()
    prefix = trigger_prefix.lower()
    if not lowered.startswith(prefix):
        return False

    query = lowered[len(prefix) :].strip()
    if not query.startswith("whitelist"):
        return False

    parts = query.split()
    if len(parts) < 2:
        usage = f"{trigger_prefix.strip()} whitelist <add|remove|list>"
        await reply_or_edit(message, is_owner, f"{X_MARK} Usage: `{usage}`")
        return True

    subcommand = parts[1].lower()
    is_admin = is_owner or message.author.id in ALLOWED_ADMIN_IDS

    if subcommand == "list":
        ids = whitelist.list_all()
        if not ids:
            await reply_or_edit(message, is_owner, f"{CHECK_MARK} Whitelist is empty.")
        else:
            formatted = ", ".join(f"<@{uid}>" for uid in ids)
            await reply_or_edit(message, is_owner, f"{CHECK_MARK} Whitelisted: {formatted}")
        return True

    if subcommand in ("add", "remove"):
        if not is_admin:
            await reply_or_edit(
                message,
                is_owner,
                f"{X_MARK} You don't have permission to modify the whitelist.",
            )
            return True

        mention_match = _MENTION_RE.search(content)
        if mention_match is not None:
            target_id = int(mention_match.group(1))
        elif len(parts) >= 3 and parts[2].isdigit():
            target_id = int(parts[2])
        else:
            usage = f"{trigger_prefix.strip()} whitelist {subcommand} @user"
            await reply_or_edit(
                message,
                is_owner,
                f"{X_MARK} Mention a user or provide an ID: `{usage}`",
            )
            return True

        if subcommand == "add":
            added = whitelist.add(target_id)
            if added:
                await reply_or_edit(
                    message, is_owner, f"{CHECK_MARK} <@{target_id}> added to whitelist."
                )
            else:
                await reply_or_edit(
                    message, is_owner, f"{WARNING_MARK} <@{target_id}> is already whitelisted."
                )
        else:
            removed = whitelist.remove(target_id)
            if removed:
                await reply_or_edit(
                    message, is_owner, f"{CHECK_MARK} <@{target_id}> removed from whitelist."
                )
            else:
                await reply_or_edit(
                    message, is_owner, f"{WARNING_MARK} <@{target_id}> is not whitelisted."
                )
        return True

    await reply_or_edit(message, is_owner, f"{X_MARK} Unknown subcommand: `{subcommand}`")
    return True
