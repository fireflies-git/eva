"""Admin social commands: joining servers and resolving friend requests."""

from __future__ import annotations

import re
from typing import Protocol

import discord

from eva.captcha import NopeCHAError
from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.discord.command_outcome import CommandOutcome
from eva.discord.commands import is_admin_user

_JOIN_COMMAND = "join"
_FRIENDS_COMMAND = "friends"
_FRIENDS_ACTIONS = frozenset({"accept", "deny"})

_MENTION_RE = re.compile(r"<@!?(\d+)>")


class SocialClient(Protocol):
    async def accept_invite(self, url: str, /) -> discord.Invite: ...

    def get_relationship(self, user_id: int, /) -> discord.Relationship | None: ...


async def handle_social_command(
    *,
    content: str,
    user_id: int,
    is_owner: bool,
    trigger_prefix: str,
    client: SocialClient | None,
) -> CommandOutcome:
    parsed = _parse_social_query(content=content, trigger_prefix=trigger_prefix)
    if parsed is None:
        return CommandOutcome.not_handled()

    if not is_admin_user(user_id=user_id, is_owner=is_owner):
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} You don't have permission to use social commands.",
        )

    if client is None:
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} Discord client is unavailable.",
        )

    command, argument = parsed
    if command == _JOIN_COMMAND:
        return await _handle_join(
            client=client,
            argument=argument,
            trigger_prefix=trigger_prefix,
        )
    return await _handle_friends_command(
        client=client,
        argument=argument,
        trigger_prefix=trigger_prefix,
    )


async def _handle_join(
    *,
    client: SocialClient,
    argument: str,
    trigger_prefix: str,
) -> CommandOutcome:
    if not argument:
        usage = f"{trigger_prefix.strip()} join <invite>"
        return CommandOutcome(handled=True, content=f"{X_MARK} Usage: `{usage}`")

    try:
        await client.accept_invite(argument)
    except discord.CaptchaRequired as exc:
        # Raised only when no captcha handler is wired in; NopeCHA failures
        # surface as NopeCHAError below instead.
        return CommandOutcome(
            handled=True,
            content=f"{WARNING_MARK} Join blocked by captcha and no solver is available: {exc}",
        )
    except NopeCHAError as exc:
        return CommandOutcome(
            handled=True,
            content=f"{WARNING_MARK} Captcha solver failed: {exc}",
        )
    except Exception as exc:
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} Join failed: {exc}",
        )

    return CommandOutcome(
        handled=True,
        content=f"{CHECK_MARK} Invite accepted.",
    )


async def _handle_friends_command(
    *,
    client: SocialClient,
    argument: str,
    trigger_prefix: str,
) -> CommandOutcome:
    parts = argument.split()
    usage = f"{trigger_prefix.strip()} friends <accept|deny> @user"
    if not parts or parts[0].lower() not in _FRIENDS_ACTIONS:
        return CommandOutcome(handled=True, content=f"{X_MARK} Usage: `{usage}`")

    target_id = _parse_target_id(argument)
    if target_id is None:
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} Mention a user or provide an ID: `{usage}`",
        )

    relationship = client.get_relationship(target_id)
    if (
        relationship is None
        or relationship.type is not discord.RelationshipType.incoming_request
    ):
        return CommandOutcome(
            handled=True,
            content=f"{WARNING_MARK} No incoming friend request from <@{target_id}>.",
        )

    action = parts[0].lower()
    try:
        if action == "accept":
            await relationship.accept()
        else:
            await relationship.delete()
    except NopeCHAError as exc:
        return CommandOutcome(
            handled=True,
            content=f"{WARNING_MARK} Captcha solver failed: {exc}",
        )
    except Exception as exc:
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} Failed to {action} friend request: {exc}",
        )

    verb = "Accepted" if action == "accept" else "Denied"
    return CommandOutcome(
        handled=True,
        content=f"{CHECK_MARK} {verb} friend request from <@{target_id}>.",
    )


def _parse_social_query(*, content: str, trigger_prefix: str) -> tuple[str, str] | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None

    remainder = text[len(prefix) :].lstrip()
    lowered = remainder.lower()
    for command in (_JOIN_COMMAND, _FRIENDS_COMMAND):
        if lowered == command:
            return (command, "")
        if lowered.startswith(f"{command} "):
            return (command, remainder[len(command) :].strip())
    return None


def _parse_target_id(content: str) -> int | None:
    mention_match = _MENTION_RE.search(content)
    if mention_match is not None:
        return int(mention_match.group(1))
    for token in content.split():
        if token.isdigit():
            return int(token)
    return None
