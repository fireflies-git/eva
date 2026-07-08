from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import discord

from eva.discord.user_metadata import (
    build_requester_context,
    build_user_metadata,
    format_user_metadata,
)


def test_user_metadata_uses_supported_profile_fields() -> None:
    user = SimpleNamespace(
        id=123,
        name="neo",
        display_name="Neo",
        bio="The One",
    )

    metadata = build_user_metadata(user)

    assert metadata.user_id == 123
    assert metadata.username == "neo"
    assert metadata.display_name == "Neo"
    assert metadata.bio == "The One"


def test_user_metadata_ignores_unavailable_pronoun_attributes() -> None:
    user = SimpleNamespace(
        id=999,
        name="sarah_7",
        display_name="Sarah",
        pronouns="she/her",
        pronoun="she/her",
    )

    metadata = build_user_metadata(user)

    assert format_user_metadata(metadata) == (
        "user(id=999, username=sarah_7, display_name=Sarah, bio=unknown)"
    )


def test_user_metadata_does_not_infer_pronouns_from_names() -> None:
    user = SimpleNamespace(id=999, name="sarah_7", display_name="Sarah")

    metadata = build_user_metadata(user)

    assert "pronouns=" not in format_user_metadata(metadata)


def test_build_requester_context_includes_mentions() -> None:
    author = SimpleNamespace(id=1, name="neo", display_name="Neo")
    mention = SimpleNamespace(id=2, name="trinity", display_name="Trinity")
    message = SimpleNamespace(author=author, mentions=[mention])

    context = build_requester_context(cast(discord.Message, message))

    assert "requester:" in context
    assert "mentions:" in context
    assert format_user_metadata(build_user_metadata(mention)) in context
