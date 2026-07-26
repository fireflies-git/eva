from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import discord


@dataclass(frozen=True, slots=True)
class UserMetadata:
    user_id: int | None
    username: str
    display_name: str
    global_name: str
    server_name: str | None
    bio: str


def build_user_metadata(user: object) -> UserMetadata:
    user_id = _optional_int_attr(user, "id")
    username = _string_attr(user, "name", default="unknown")
    display_name = _string_attr(user, "display_name", default=username)
    global_name = _string_attr(user, "global_name", default=display_name)
    server_name = _optional_server_name(user, display_name)
    bio = _read_bio(user)

    return UserMetadata(
        user_id=user_id,
        username=username,
        display_name=display_name,
        global_name=global_name,
        server_name=server_name,
        bio=bio,
    )


def format_user_metadata(metadata: UserMetadata) -> str:
    """Format user as a compact readable label for AI context.

    Produces forms like:
        @Leah (leah)             -- server nick == global name
        @DevLeah (leah)          -- server nick differs, shown as display
        @Leah | sr:DevLeah (leah)  -- server nick differs from display name
    """
    user_id = str(metadata.user_id) if metadata.user_id is not None else "0"
    primary = metadata.display_name
    extras: list[str] = []

    if metadata.server_name is not None and metadata.server_name != primary:
        extras.append(f"sr:{metadata.server_name}")
    if metadata.global_name != primary:
        extras.append(f"gl:{metadata.global_name}")

    tag = metadata.username
    if tag == "unknown":
        tag = user_id

    base = f"@{primary}"
    if extras:
        base += " | " + " ".join(extras)
    return f"{base} ({tag})"


def format_mentions_metadata(mentions: Sequence[object]) -> str | None:
    if not mentions:
        return None
    rendered = "; ".join(format_user_metadata(build_user_metadata(user)) for user in mentions)
    return f"mentions: {rendered}"


def build_requester_context(message: discord.Message) -> str:
    requester = format_user_metadata(build_user_metadata(message.author))
    mentions = format_mentions_metadata(list(getattr(message, "mentions", [])))

    lines = [f"requester: {requester}"]
    if mentions:
        lines.append(mentions)
    return "\n".join(lines)


def _optional_server_name(user: object, display_name: str) -> str | None:
    nick = getattr(user, "nick", None)
    if isinstance(nick, str) and nick.strip() and nick.strip() != display_name:
        return nick.strip()
    return None


def _optional_int_attr(obj: object, name: str) -> int | None:
    value = getattr(obj, name, None)
    return value if isinstance(value, int) else None


def _string_attr(obj: object, name: str, *, default: str) -> str:
    value = getattr(obj, name, None)
    if isinstance(value, str):
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return default


def _read_bio(user: object) -> str:
    for key in ("bio", "about_me", "global_name"):
        value = getattr(user, key, None)
        if isinstance(value, str):
            cleaned = _clean_text(value)
            if cleaned:
                return cleaned
    return "unknown"


def _clean_text(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    return cleaned[:200]
