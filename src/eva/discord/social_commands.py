"""Admin social commands: joining servers and resolving friend requests."""

from __future__ import annotations

import re
from typing import Protocol, cast

import discord

from eva.captcha import NopeCHAError
from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.discord.command_outcome import CommandOutcome
from eva.discord.commands import is_admin_user
from eva.discord.friend_requests import FriendRequestDecision, FriendRequestHandler

_JOIN_COMMAND = "join"
_FRIENDS_COMMAND = "friends"
_REVIEW_COMMAND = "review"
_DIRECT_FRIEND_ACTIONS = frozenset({"accept", "deny"})
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
    friend_request_handler: FriendRequestHandler | None = None,
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
    if command == _REVIEW_COMMAND:
        return await _handle_targeted_friend_command(
            client=client,
            friend_request_handler=friend_request_handler,
            admin_user_id=user_id,
            action=_REVIEW_COMMAND,
            argument=argument,
            trigger_prefix=trigger_prefix,
        )
    if command in _DIRECT_FRIEND_ACTIONS:
        return await _handle_targeted_friend_command(
            client=client,
            friend_request_handler=friend_request_handler,
            admin_user_id=user_id,
            action=command,
            argument=argument,
            trigger_prefix=trigger_prefix,
        )
    return await _handle_friends_command(
        client=client,
        argument=argument,
        trigger_prefix=trigger_prefix,
        friend_request_handler=friend_request_handler,
        admin_user_id=user_id,
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
    friend_request_handler: FriendRequestHandler | None,
    admin_user_id: int,
) -> CommandOutcome:
    parts = argument.split()
    usage = f"{trigger_prefix.strip()} friends <accept|deny> @user"
    if not parts or parts[0].lower() not in _FRIENDS_ACTIONS:
        return CommandOutcome(handled=True, content=f"{X_MARK} Usage: `{usage}`")

    target_id = _parse_target_id(argument)
    action = parts[0].lower()
    if friend_request_handler is not None:
        pending_result = await friend_request_handler.handle_targeted_decision(
            client=cast(discord.Client, client),
            admin_user_id=admin_user_id,
            requester_id=target_id,
            decision=(
                FriendRequestDecision.ACCEPT
                if action == "accept"
                else FriendRequestDecision.DENY
            ),
        )
        if pending_result is not None:
            return CommandOutcome(handled=True, content=pending_result)

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


async def _handle_targeted_friend_command(
    *,
    client: SocialClient,
    friend_request_handler: FriendRequestHandler | None,
    admin_user_id: int,
    action: str,
    argument: str,
    trigger_prefix: str,
) -> CommandOutcome:
    usage = f"{trigger_prefix.strip()} {action} [@user]"
    target_id = _parse_target_id(argument, allow_numeric=False)
    if friend_request_handler is None:
        if target_id is None:
            return CommandOutcome(handled=True, content=f"{X_MARK} Usage: `{usage}`")
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} Friend request handling is unavailable.",
        )

    if action == _REVIEW_COMMAND:
        content = await friend_request_handler.handle_targeted_review(
            client=cast(discord.Client, client),
            admin_user_id=admin_user_id,
            requester_id=target_id,
        )
    else:
        result = await friend_request_handler.handle_targeted_decision(
            client=cast(discord.Client, client),
            admin_user_id=admin_user_id,
            requester_id=target_id,
            decision=(
                FriendRequestDecision.ACCEPT
                if action == "accept"
                else FriendRequestDecision.DENY
            ),
        )
        if result is None:
            if target_id is None:
                return CommandOutcome(
                    handled=True,
                    content=f"{WARNING_MARK} You have no pending friend requests to resolve.",
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
            content = f"{CHECK_MARK} {verb} friend request from <@{target_id}>."
        else:
            content = result
    return CommandOutcome(handled=True, content=content)


def _parse_social_query(*, content: str, trigger_prefix: str) -> tuple[str, str] | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None

    remainder = text[len(prefix) :].lstrip()
    lowered = remainder.lower()
    for command in (
        _JOIN_COMMAND,
        _FRIENDS_COMMAND,
        _REVIEW_COMMAND,
        *_DIRECT_FRIEND_ACTIONS,
    ):
        if lowered == command:
            return (command, "")
        if lowered.startswith(f"{command} "):
            return (command, remainder[len(command) :].strip())
    return None


def _parse_target_id(content: str, *, allow_numeric: bool = True) -> int | None:
    mention_match = _MENTION_RE.search(content)
    if mention_match is not None:
        return int(mention_match.group(1))
    if allow_numeric:
        for token in content.split():
            if token.isdigit():
                return int(token)
    return None
