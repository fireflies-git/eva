"""Friend request pipeline: review, admin DM fan-out, and resolution."""

from __future__ import annotations

import enum
import logging
from collections.abc import Iterable, Sequence
from typing import Protocol

import discord

from eva.ai.friend_request_review import FriendRequestReview
from eva.captcha import NopeCHAError
from eva.constants import (
    CHECK_MARK,
    FRIEND_REQUEST_IGNORE_BOTS,
    FRIEND_REQUEST_PROFILE_MUTUAL_FRIENDS_LIMIT,
    FRIEND_REQUEST_PROFILE_MUTUAL_GUILDS_LIMIT,
    WARNING_MARK,
    X_MARK,
)
from eva.state import PendingFriendRequest, PendingFriendRequestStore

logger = logging.getLogger(__name__)

_ACCEPT_WORDS = frozenset({"yes", "y", "accept"})
_DENY_WORDS = frozenset({"no", "n", "deny", "reject"})


class FriendRequestDecision(enum.Enum):
    ACCEPT = "accept"
    DENY = "deny"


class FriendRequestReviewer(Protocol):
    async def review(self, profile_text: str) -> FriendRequestReview | None: ...


class FriendRequestHandler:
    def __init__(
        self,
        *,
        pending_store: PendingFriendRequestStore,
        review_service: FriendRequestReviewer | None = None,
        admin_ids: Iterable[int] = (),
    ) -> None:
        self._pending_store = pending_store
        self._review_service = review_service
        self._admin_ids = set(admin_ids)

    async def handle_incoming_request(
        self,
        *,
        client: discord.Client,
        relationship: discord.Relationship,
    ) -> None:
        if relationship.type is not discord.RelationshipType.incoming_request:
            return
        user = relationship.user
        if FRIEND_REQUEST_IGNORE_BOTS and getattr(user, "bot", False):
            logger.info("Ignoring bot friend request from %s", user.id)
            return

        profile_text = await _fetch_profile_text(client, user)
        review = await self._review(_build_review_input(user, profile_text))
        body = build_friend_request_dm(user, profile_text, review)

        admin_ids = self._admin_ids
        owner_id = client.user.id if client.user is not None else None
        if owner_id is not None:
            admin_ids = admin_ids | {owner_id}

        notified = await _fan_out_dm(client, sorted(admin_ids), body)
        if not notified:
            logger.warning(
                "No admin DM delivered for friend request from %s; "
                "leaving the request pending for manual handling",
                user.id,
            )
            return

        self._pending_store.set(
            requester_id=user.id,
            requester_label=_label_user(user),
            review_text=body,
            notified_admin_ids=frozenset(notified),
        )
        logger.info(
            "Friend request from %s pending admin decision (notified: %s)",
            user.id,
            notified,
        )

    async def handle_confirmation(
        self,
        *,
        client: discord.Client,
        admin_user_id: int,
        content: str,
    ) -> str | None:
        """Resolve the oldest pending request this admin was notified about.

        Returns None when the message is not a yes/no reply or there is no
        matching pending request (the message then falls through to normal
        handling). Otherwise returns the confirmation text for the admin.
        """
        decision = parse_friend_request_confirmation(content)
        if decision is None:
            return None
        pending = self._pending_store.pop_oldest_for_admin(admin_user_id=admin_user_id)
        if pending is None:
            return None
        return await self._resolve_pending(
            client=client,
            pending=pending,
            decision=decision,
        )

    def is_requester_pending(self, *, requester_id: int) -> bool:
        return self._pending_store.get(requester_id=requester_id) is not None

    async def notify_pending_requests(self, *, client: discord.Client) -> None:
        admin_ids = set(self._admin_ids)
        if client.user is not None:
            admin_ids.add(client.user.id)

        for pending in self._pending_store.list_pending():
            recipients = sorted(set(pending.notified_admin_ids) | admin_ids)
            body = (
                "Eva restarted, and this friend request is still pending review.\n\n"
                f"{pending.review_text}\n\n"
                "You can use `eva review`, `eva accept`, or `eva deny` for the "
                "most recent pending request."
            )
            notified = await _fan_out_dm(client, recipients, body)
            if notified:
                self._pending_store.add_notified_admins(
                    requester_id=pending.requester_id,
                    admin_ids=frozenset(notified),
                )

    async def handle_targeted_review(
        self,
        *,
        client: discord.Client,
        admin_user_id: int,
        requester_id: int | None,
    ) -> str:
        pending = (
            self._pending_store.pop_latest_for_admin(admin_user_id=admin_user_id)
            if requester_id is None
            else self._pending_store.pop_for_admin(
                requester_id=requester_id,
                admin_user_id=admin_user_id,
            )
        )
        if pending is None:
            return self._missing_target_message(requester_id)
        return await self._resolve_pending(
            client=client,
            pending=pending,
            decision=FriendRequestDecision.ACCEPT,
            application_admin_id=admin_user_id,
        )

    async def handle_targeted_decision(
        self,
        *,
        client: discord.Client,
        admin_user_id: int,
        requester_id: int | None,
        decision: FriendRequestDecision,
    ) -> str | None:
        if requester_id is None:
            pending = self._pending_store.pop_latest_for_admin(admin_user_id=admin_user_id)
            if pending is None:
                return self._missing_target_message(None)
            return await self._resolve_pending(
                client=client,
                pending=pending,
                decision=decision,
            )

        pending = self._pending_store.get(requester_id=requester_id)
        if pending is not None and admin_user_id not in pending.notified_admin_ids:
            return self._missing_target_message(requester_id)
        if pending is not None:
            pending = self._pending_store.pop_for_admin(
                requester_id=requester_id,
                admin_user_id=admin_user_id,
            )
        if pending is not None:
            return await self._resolve_pending(
                client=client,
                pending=pending,
                decision=decision,
            )
        return None

    async def _review(
        self,
        profile_text: str,
    ) -> FriendRequestReview | None:
        if self._review_service is None:
            return None
        try:
            return await self._review_service.review(profile_text)
        except Exception:
            # A review failure must not block the request from reaching admins.
            logger.exception("Friend request review failed")
            return None

    async def _resolve_pending(
        self,
        *,
        client: discord.Client,
        pending: PendingFriendRequest,
        decision: FriendRequestDecision,
        application_admin_id: int | None = None,
    ) -> str:
        relationship = client.get_relationship(pending.requester_id)
        if (
            relationship is None
            or relationship.type is not discord.RelationshipType.incoming_request
        ):
            return (
                f"{WARNING_MARK} Friend request from {pending.requester_label} "
                "is already resolved or no longer exists."
            )

        action = decision.value
        try:
            if decision is FriendRequestDecision.ACCEPT:
                await relationship.accept()
            else:
                await relationship.delete()
        except NopeCHAError as exc:
            self._restore_pending(pending)
            return f"{WARNING_MARK} Captcha solver failed while {action}ing: {exc}"
        except Exception as exc:
            self._restore_pending(pending)
            return f"{X_MARK} Failed to {action} friend request: {exc}"

        verb = "Accepted" if decision is FriendRequestDecision.ACCEPT else "Denied"
        if application_admin_id is not None:
            try:
                await self._create_application_group(
                    client=client,
                    pending=pending,
                    admin_user_id=application_admin_id,
                    requester=relationship.user,
                )
            except Exception as exc:
                logger.exception(
                    "Failed to create application group for friend request from %s",
                    pending.requester_id,
                )
                return (
                    f"{CHECK_MARK} Accepted friend request from {pending.requester_label}, "
                    f"but application group setup failed: {exc}"
                )
        return f"{CHECK_MARK} {verb} friend request from {pending.requester_label}."

    async def _create_application_group(
        self,
        *,
        client: discord.Client,
        pending: PendingFriendRequest,
        admin_user_id: int,
        requester: discord.User,
    ) -> None:
        admin = client.get_user(admin_user_id)
        if admin is None:
            admin = await client.fetch_user(admin_user_id)
        group = await client.create_group(admin, requester)
        await group.edit(name=f"{pending.requester_label}'s Application")
        await group.send(
            f"Application started for **{pending.requester_label}**. "
            f"<@{admin_user_id}> and <@{pending.requester_id}>, please discuss the request here."
        )

    @staticmethod
    def _missing_target_message(requester_id: int | None) -> str:
        if requester_id is None:
            return f"{WARNING_MARK} You have no pending friend requests to resolve."
        return (
            f"{WARNING_MARK} No pending friend request for <@{requester_id}> "
            "that you are assigned to review."
        )

    def _restore_pending(self, pending: PendingFriendRequest) -> None:
        self._pending_store.set(
            requester_id=pending.requester_id,
            requester_label=pending.requester_label,
            review_text=pending.review_text,
            notified_admin_ids=pending.notified_admin_ids,
        )


async def _fetch_profile_text(
    client: discord.Client,
    user: discord.User,
) -> str:
    try:
        profile = await client.fetch_user_profile(user.id)
    except Exception:
        logger.exception("Failed to fetch profile for %s; using basic info", user.id)
        return _serialize_basic_user(user)
    return serialize_profile(profile)


def serialize_profile(profile: discord.UserProfile) -> str:
    lines = [f"Name: {_format_username(profile)}"]
    if getattr(profile, "display_name", None):
        lines.append(f"Display name: {profile.display_name}")
    if profile.bio:
        lines.append(f"Bio: {profile.bio}")

    badges = getattr(profile, "badges", ())
    if badges:
        badge_names = [str(badge) or badge.id for badge in badges]
        lines.append(f"Badges: {', '.join(badge_names)}")

    mutual_friends = profile.mutual_friends
    if mutual_friends:
        names = _user_names(
            mutual_friends,
            limit=FRIEND_REQUEST_PROFILE_MUTUAL_FRIENDS_LIMIT,
        )
        count = profile.mutual_friends_count or len(mutual_friends)
        lines.append(f"Mutual friends ({count}): {', '.join(names)}")

    mutual_guilds = profile.mutual_guilds
    if mutual_guilds:
        names = [
            _mutual_guild_name(guild)
            for guild in mutual_guilds[:FRIEND_REQUEST_PROFILE_MUTUAL_GUILDS_LIMIT]
        ]
        lines.append(f"Mutual guilds ({len(mutual_guilds)}): {', '.join(names)}")

    return "\n".join(lines)


def build_friend_request_dm(
    user: discord.User,
    profile_text: str,
    review: FriendRequestReview | None,
) -> str:
    if review is not None:
        lines = [review.message]
    else:
        lines = [
            f"I got a friend request from **{_label_user(user)}** "
            f"(`{_format_username(user)}`, {user.id}).",
            "",
            "Here are the profile details I could retrieve:",
            profile_text,
            "",
            "I do not have enough information to say whether I would trust this request yet.",
        ]
    lines.extend(
        [
            "",
            "Reply `y` to accept it. Reply `n` to deny it.",
        ]
    )
    return "\n".join(lines)


def parse_friend_request_confirmation(content: str) -> FriendRequestDecision | None:
    normalized = content.strip().lower()
    if normalized in _ACCEPT_WORDS:
        return FriendRequestDecision.ACCEPT
    if normalized in _DENY_WORDS:
        return FriendRequestDecision.DENY
    return None


async def _fan_out_dm(
    client: discord.Client,
    admin_ids: Sequence[int],
    body: str,
) -> list[int]:
    notified: list[int] = []
    for admin_id in admin_ids:
        try:
            user = client.get_user(admin_id)
            if user is None:
                user = await client.fetch_user(admin_id)
            await user.send(body)
        except Exception:
            logger.exception("Failed to DM admin %s about friend request", admin_id)
            continue
        notified.append(admin_id)
    return notified


def _serialize_basic_user(user: discord.User) -> str:
    return f"Name: {_format_username(user)}"


def _build_review_input(user: discord.User, profile_text: str) -> str:
    return (
        f"Requester display label: {_label_user(user)}\n"
        f"Requester ID: {user.id}\n\n"
        f"Public profile:\n{profile_text}"
    )


def _label_user(user: discord.User) -> str:
    display_name = getattr(user, "display_name", None)
    if isinstance(display_name, str) and display_name:
        return display_name
    return _format_username(user)


def _format_username(user: discord.User) -> str:
    name = getattr(user, "name", "unknown")
    discriminator = getattr(user, "discriminator", None)
    if discriminator and discriminator != "0":
        return f"{name}#{discriminator}"
    return str(name)


def _user_names(users: Sequence[discord.User], *, limit: int) -> list[str]:
    names: list[str] = []
    for user in users[:limit]:
        names.append(_label_user(user))
    return names


def _mutual_guild_name(mutual_guild: object) -> str:
    guild = getattr(mutual_guild, "guild", None)
    name = getattr(guild, "name", None)
    if isinstance(name, str) and name:
        return name
    nick = getattr(mutual_guild, "nick", None)
    if isinstance(nick, str) and nick:
        return nick
    return "?"
