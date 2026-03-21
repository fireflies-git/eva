from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

import discord

_KNOWN_PRONOUNS = {
    "he/him",
    "she/her",
    "they/them",
    "he/they",
    "she/they",
    "they/he",
    "they/she",
    "it/its",
    "xe/xem",
    "ze/zir",
    "any/all",
    "any pronouns",
}

_FEMININE_HINTS = {
    "alice",
    "anna",
    "bella",
    "emily",
    "emma",
    "julia",
    "lily",
    "luna",
    "mia",
    "olivia",
    "sarah",
    "sophia",
}

_MASCULINE_HINTS = {
    "alex",
    "ben",
    "charlie",
    "david",
    "ethan",
    "jack",
    "james",
    "john",
    "leo",
    "liam",
    "lucas",
    "michael",
    "noah",
}


@dataclass(frozen=True, slots=True)
class UserMetadata:
    user_id: int | None
    username: str
    display_name: str
    pronouns: str
    bio: str


def build_user_metadata(user: object) -> UserMetadata:
    user_id = _optional_int_attr(user, "id")
    username = _string_attr(user, "name", default="unknown")
    display_name = _string_attr(user, "display_name", default=username)
    raw_pronouns = _read_raw_pronouns(user)
    pronouns = _normalize_pronouns(
        raw_pronouns,
        display_name=display_name,
        username=username,
    )
    bio = _read_bio(user)

    return UserMetadata(
        user_id=user_id,
        username=username,
        display_name=display_name,
        pronouns=pronouns,
        bio=bio,
    )


def format_user_metadata(metadata: UserMetadata) -> str:
    user_id = str(metadata.user_id) if metadata.user_id is not None else "unknown"
    return (
        "user("
        f"id={user_id}, "
        f"username={metadata.username}, "
        f"display_name={metadata.display_name}, "
        f"pronouns={metadata.pronouns}, "
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


def _read_raw_pronouns(user: object) -> str | None:
    for key in ("pronouns", "pronoun"):
        value = getattr(user, key, None)
        if isinstance(value, str):
            cleaned = _clean_text(value)
            if cleaned:
                return cleaned
    return None


def _read_bio(user: object) -> str:
    for key in ("bio", "about_me", "global_name"):
        value = getattr(user, key, None)
        if isinstance(value, str):
            cleaned = _clean_text(value)
            if cleaned:
                return cleaned
    return "unknown"


def _normalize_pronouns(raw: str | None, *, display_name: str, username: str) -> str:
    if raw is not None and _looks_like_pronouns(raw):
        return raw.lower()
    return _infer_pronouns(display_name=display_name, username=username)


def _looks_like_pronouns(value: str) -> bool:
    normalized = value.strip().lower()
    if not normalized or len(normalized) > 40:
        return False
    if normalized in _KNOWN_PRONOUNS:
        return True
    if "/" not in normalized:
        return False

    parts = [part for part in re.split(r"[\s/]+", normalized) if part]
    if len(parts) < 2 or len(parts) > 4:
        return False
    return all(part.isalpha() and len(part) <= 12 for part in parts)


def _infer_pronouns(*, display_name: str, username: str) -> str:
    combined = f"{display_name} {username}".lower()
    first_token = _extract_name_token(display_name) or _extract_name_token(username)

    if "girl" in combined or "queen" in combined or "princess" in combined:
        return "she/her"
    if "boy" in combined or "king" in combined or "prince" in combined:
        return "he/him"
    if first_token in _FEMININE_HINTS:
        return "she/her"
    if first_token in _MASCULINE_HINTS:
        return "he/him"
    return "they/them"


def _extract_name_token(value: str) -> str:
    token = value.strip().split(" ")[0].lower()
    return re.sub(r"[^a-z]", "", token)


def _clean_text(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    return cleaned[:200]
