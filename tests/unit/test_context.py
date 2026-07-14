from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import cast

import discord

from eva.discord.context import fetch_channel_context, fetch_reply_context


class _FakeHistoryChannel:
    def __init__(self, messages: list[object]) -> None:
        self._messages = messages

    async def history(self, *, limit: int, oldest_first: bool) -> object:
        for message in self._messages[:limit]:
            yield message


class _FakeReplyChannel:
    def __init__(self, message: object) -> None:
        self._message = message

    async def fetch_message(self, message_id: int) -> object:
        return self._message


def _make_author(**kwargs: object) -> object:
    return SimpleNamespace(**kwargs)


def _make_message(
    *,
    msg_id: int,
    content: str,
    author: object,
    created_at: datetime | None = None,
    mentions: list[object] | None = None,
    reactions: list[object] | None = None,
    reference: object | None = None,
    edited_at: datetime | None = None,
    attachments: list[object] | None = None,
) -> object:
    fields: dict[str, object] = {
        "id": msg_id,
        "content": content,
        "author": author,
        "created_at": created_at or datetime(2026, 1, 1, 12, 0),
        "mentions": mentions or [],
        "reactions": reactions or [],
        "reference": reference,
        "edited_at": edited_at,
        "attachments": attachments or [],
    }
    return SimpleNamespace(**fields)


def _make_reaction(emoji: object, count: int) -> object:
    return SimpleNamespace(emoji=emoji, count=count)


class _FakeCustomEmoji:
    def __init__(self, name: str) -> None:
        self.name = name


def test_fetch_channel_context_includes_user_and_mentions() -> None:
    mention = _make_author(id=2, name="trinity", display_name="Trinity")
    author = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="hello there",
        author=author,
        mentions=[mention],
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
            exclude_message_id=None,
        )
    )

    assert len(context) == 1
    assert "username=neo" in context[0]["content"]
    assert "display_name=Neo" in context[0]["content"]
    assert "pronouns=" not in context[0]["content"]
    assert "mentions:" in context[0]["content"]
    assert "username=trinity" in context[0]["content"]


def test_fetch_reply_context_includes_user_metadata() -> None:
    reply_author = _make_author(id=7, name="neo", display_name="Neo")
    referenced_message = _make_message(
        msg_id=123,
        content="previous message",
        author=reply_author,
    )
    channel = _FakeReplyChannel(referenced_message)
    message = _make_message(
        msg_id=10,
        content="reply message",
        author=_make_author(id=1, name="eva", display_name="Eva"),
        reference=SimpleNamespace(message_id=123),
    )
    message.channel = channel

    reply_context = asyncio.run(fetch_reply_context(cast(discord.Message, message)))

    assert reply_context is not None
    assert "username=neo" in reply_context
    assert "pronouns=" not in reply_context
    assert "previous message" in reply_context


def test_channel_context_includes_reactions() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="nice post",
        author=author,
        reactions=[_make_reaction("👍", 2), _make_reaction("❤️", 1)],
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 1
    assert "👍 2" in context[0]["content"]
    assert "❤️ 1" in context[0]["content"]


def test_channel_context_includes_custom_emoji_reactions() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="custom",
        author=author,
        reactions=[_make_reaction(_FakeCustomEmoji("catthumbsup"), 3)],
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 1
    assert ":catthumbsup: 3" in context[0]["content"]


def test_channel_context_includes_reply_target_when_in_batch() -> None:
    alice = _make_author(id=1, name="alice", display_name="Alice")
    bob = _make_author(id=2, name="bob", display_name="Bob")
    bobs_message = _make_message(
        msg_id=5,
        content="original thought",
        author=bob,
        created_at=datetime(2026, 1, 1, 12, 0),
    )
    alices_reply = _make_message(
        msg_id=10,
        content="I agree",
        author=alice,
        created_at=datetime(2026, 1, 1, 12, 1),
        reference=SimpleNamespace(message_id=5),
    )
    channel = _FakeHistoryChannel([alices_reply, bobs_message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 2
    alice_line = context[1]["content"]
    assert "reply to @Bob" in alice_line


def test_channel_context_shows_generic_reply_when_target_not_in_batch() -> None:
    alice = _make_author(id=1, name="alice", display_name="Alice")
    message = _make_message(
        msg_id=10,
        content="replying to something far back",
        author=alice,
        reference=SimpleNamespace(message_id=1),
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 1
    assert "reply" in context[0]["content"]
    assert "reply to @" not in context[0]["content"]


def test_channel_context_includes_edited_marker() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="fixed typo",
        author=author,
        edited_at=datetime(2026, 1, 1, 12, 5),
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 1
    assert "edited" in context[0]["content"]


def test_channel_context_includes_single_attachment() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="check this out",
        author=author,
        attachments=[SimpleNamespace(filename="photo.png")],
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 1
    assert "attached: photo.png" in context[0]["content"]


def test_channel_context_includes_multiple_attachments() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="here are files",
        author=author,
        attachments=[
            SimpleNamespace(filename="a.py"),
            SimpleNamespace(filename="b.png"),
        ],
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 1
    assert "attached: a.py, b.png" in context[0]["content"]


def test_channel_context_has_no_extras_when_message_is_plain() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="just a normal message",
        author=author,
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 1
    content = context[0]["content"]
    assert " | " not in content
    assert "edited" not in content
    assert "reply" not in content
    assert "attached:" not in content


def test_channel_context_combines_multiple_extras() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="rich message",
        author=author,
        reactions=[_make_reaction("👍", 1)],
        edited_at=datetime(2026, 1, 1, 12, 5),
        attachments=[SimpleNamespace(filename="doc.pdf")],
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 1
    content = context[0]["content"]
    assert "edited" in content
    assert "👍 1" in content
    assert "attached: doc.pdf" in content


def test_fetch_reply_context_includes_reactions_on_referenced_message() -> None:
    reply_author = _make_author(id=7, name="neo", display_name="Neo")
    referenced_message = _make_message(
        msg_id=123,
        content="check this",
        author=reply_author,
        reactions=[_make_reaction("👀", 4)],
    )
    channel = _FakeReplyChannel(referenced_message)
    message = _make_message(
        msg_id=10,
        content="what about it",
        author=_make_author(id=1, name="eva", display_name="Eva"),
        reference=SimpleNamespace(message_id=123),
    )
    message.channel = channel

    reply_context = asyncio.run(fetch_reply_context(cast(discord.Message, message)))

    assert reply_context is not None
    assert "👀 4" in reply_context
    assert "previous" not in reply_context


def test_fetch_channel_context_excludes_message_by_id() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    msg1 = _make_message(msg_id=10, content="keep me", author=author)
    msg2 = _make_message(msg_id=20, content="skip me", author=author)
    channel = _FakeHistoryChannel([msg2, msg1])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
            exclude_message_id=20,
        )
    )

    assert len(context) == 1
    assert "keep me" in context[0]["content"]


def test_channel_context_orders_oldest_first() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    older = _make_message(
        msg_id=5,
        content="first",
        author=author,
        created_at=datetime(2026, 1, 1, 12, 0),
    )
    newer = _make_message(
        msg_id=10,
        content="second",
        author=author,
        created_at=datetime(2026, 1, 1, 12, 1),
    )
    channel = _FakeHistoryChannel([newer, older])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
        )
    )

    assert len(context) == 2
    assert "first" in context[0]["content"]
    assert "second" in context[1]["content"]
