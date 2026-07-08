from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import discord


@dataclass(frozen=True, slots=True)
class UserMetadata:
    user_id: int | None
    username: str
    display_name: str
    bio: str


def build_user_metadata(user: object) -> UserMetadata:
    user_id = _optional_int_attr(user, "id")
    username = _string_attr(user, "name", default="unknown")
    display_name = _string_attr(user, "display_name", default=username)
    bio = _read_bio(user)

    return UserMetadata(
        user_id=user_id,
        username=username,
        display_name=display_name,
        bio=bio,
    )


def format_user_metadata(metadata: UserMetadata) -> str:
    user_id = str(metadata.user_id) if metadata.user_id is not None else "unknown"
    return (
        "user("
        f"id={user_id}, "
        f"username={metadata.username}, "
        f"display_name={metadata.display_name}, "
        f"bio={metadata.bio}"
        ")"
    )


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
