from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import discord

from eva.discord.user_metadata import (
    build_requester_context,
    build_user_metadata,
    format_user_metadata,
)


def test_user_metadata_uses_explicit_pronouns() -> None:
    user = SimpleNamespace(
        id=123,
        name="neo",
        display_name="Neo",
        pronouns="he/him",
        bio="The One",
    )

    metadata = build_user_metadata(user)

    assert metadata.user_id == 123
    assert metadata.username == "neo"
    assert metadata.display_name == "Neo"
    assert metadata.pronouns == "he/him"
    assert metadata.bio == "The One"


def test_user_metadata_falls_back_to_inferred_pronouns() -> None:
    user = SimpleNamespace(
        id=999,
        name="sarah_7",
        display_name="Sarah",
        pronouns="coffee lover",
    )

    metadata = build_user_metadata(user)

    assert metadata.pronouns == "she/her"


def test_user_metadata_defaults_to_they_them_when_unknown() -> None:
    user = SimpleNamespace(id=999, name="x9z1", display_name="x9z1", pronouns="")

    metadata = build_user_metadata(user)

    assert metadata.pronouns == "they/them"


def test_build_requester_context_includes_mentions() -> None:
    author = SimpleNamespace(id=1, name="neo", display_name="Neo", pronouns="he/him")
    mention = SimpleNamespace(id=2, name="trinity", display_name="Trinity", pronouns="she/her")
    message = SimpleNamespace(author=author, mentions=[mention])

    context = build_requester_context(cast(discord.Message, message))

    assert "requester:" in context
    assert "mentions:" in context
    assert format_user_metadata(build_user_metadata(mention)) in context
