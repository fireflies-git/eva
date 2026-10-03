from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

import discord

from eva.discord.context import fetch_channel_context, fetch_reply_context


class _FakeHistoryChannel:
    def __init__(
        self,
        messages: list[object],
        fetched_messages: dict[int, object] | None = None,
    ) -> None:
        self._messages = messages
        self._fetched_messages = fetched_messages or {}

    async def history(self, *, limit: int, oldest_first: bool) -> object:
        for message in self._messages[:limit]:
            yield message

    async def fetch_message(self, message_id: int) -> object:
        return self._fetched_messages[message_id]


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
    channel: object | None = None,
) -> Any:
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
        "channel": channel,
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
    assert "@Neo (neo)" in context[0]["content"]
    assert "mentions:" in context[0]["content"]
    assert "@Trinity (trinity)" in context[0]["content"]
    assert "message_id:10" in context[0]["content"]
    assert "user_id:1" in context[0]["content"]


def test_assistant_mode_only_marks_tracked_shared_account_messages_as_assistant() -> None:
    owner = _make_author(id=1, name="owner", display_name="Owner")
    eva_message = _make_message(msg_id=11, content="Eva output", author=owner)
    owner_message = _make_message(msg_id=10, content="Human output", author=owner)
    channel = _FakeHistoryChannel([eva_message, owner_message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
            bot_user_id=1,
            account_mode="assistant",
            is_tracked_message=lambda message_id: message_id == 11,
        )
    )

    assert [message["role"] for message in context] == ["user", "assistant"]


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
    assert "@Neo (neo)" in reply_context
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


def test_channel_context_fetches_reply_author_outside_context_window() -> None:
    alice = _make_author(id=1, name="alice", display_name="Alice")
    bob = _make_author(id=2, name="bob", display_name="Bob")
    referenced = _make_message(msg_id=1, content="older message", author=bob)
    reply = _make_message(
        msg_id=10,
        content="replying to something far back",
        author=alice,
        reference=SimpleNamespace(message_id=1),
    )
    channel = _FakeHistoryChannel([reply], fetched_messages={1: referenced})

    context = asyncio.run(
        fetch_channel_context(cast(discord.abc.Messageable, channel), limit=5)
    )

    assert "reply to @Bob (bob) [user_id:2] [message_id:1]" in context[0]["content"]


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


def test_channel_context_keeps_attachment_only_messages() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="",
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
    assert "[no text]" in context[0]["content"]
    assert "attached: photo.png" in context[0]["content"]


def test_channel_context_keeps_attachment_only_assistant_messages() -> None:
    assistant = _make_author(id=99, name="eva", display_name="Eva")
    message = _make_message(
        msg_id=10,
        content="",
        author=assistant,
        attachments=[SimpleNamespace(filename="generated.webp")],
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
            bot_user_id=99,
        )
    )

    assert len(context) == 1
    assert context[0]["role"] == "assistant"
    assert "attached: generated.webp" in context[0]["content"]


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


def test_fetch_reply_context_keeps_attachment_only_message() -> None:
    reply_author = _make_author(id=7, name="neo", display_name="Neo")
    referenced_message = _make_message(
        msg_id=123,
        content="",
        author=reply_author,
        attachments=[SimpleNamespace(filename="diagram.webp")],
    )
    channel = _FakeReplyChannel(referenced_message)
    message = _make_message(
        msg_id=10,
        content="describe this",
        author=_make_author(id=1, name="eva", display_name="Eva"),
        reference=SimpleNamespace(message_id=123),
        channel=channel,
    )

    reply_context = asyncio.run(fetch_reply_context(cast(discord.Message, message)))

    assert reply_context is not None
    assert "[no text]" in reply_context
    assert "attached: diagram.webp" in reply_context


def test_fetch_reply_context_can_bound_referenced_message() -> None:
    reply_author = _make_author(id=7, name="neo", display_name="Neo")
    referenced_message = _make_message(
        msg_id=123,
        content="previous message " + ("x" * 200),
        author=reply_author,
    )
    channel = _FakeReplyChannel(referenced_message)
    message = _make_message(
        msg_id=10,
        content="describe this",
        author=_make_author(id=1, name="eva", display_name="Eva"),
        reference=SimpleNamespace(message_id=123),
        channel=channel,
    )

    reply_context = asyncio.run(
        fetch_reply_context(cast(discord.Message, message), max_chars=80)
    )

    assert reply_context is not None
    assert len(reply_context) <= 80
    assert "[context truncated]" in reply_context


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


def test_channel_context_can_bound_message_and_total_sizes() -> None:
    author = _make_author(id=1, name="neo", display_name="Neo")
    older = _make_message(msg_id=5, content="older " + ("x" * 200), author=author)
    newer = _make_message(msg_id=10, content="newer " + ("y" * 200), author=author)
    channel = _FakeHistoryChannel([newer, older])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
            max_message_chars=40,
            max_total_chars=180,
        )
    )

    joined = "\n".join(str(message["content"]) for message in context)
    assert len(joined) <= 180
    assert "newer" in joined
    assert "[context truncated]" in joined


def test_channel_context_strips_watermark_from_bot_messages() -> None:
    bot = _make_author(id=99, name="eva", display_name="Eva")
    message = _make_message(
        msg_id=10,
        content="generated reply\n\n-# -eva",
        author=bot,
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
            bot_user_id=99,
        )
    )

    assert len(context) == 1
    assert context[0]["role"] == "assistant"
    assert "generated reply" in context[0]["content"]
    assert "-# -eva" not in context[0]["content"]


def test_channel_context_skips_watermark_only_bot_messages() -> None:
    bot = _make_author(id=99, name="eva", display_name="Eva")
    user = _make_author(id=1, name="neo", display_name="Neo")
    watermark_only = _make_message(msg_id=10, content="-# -eva", author=bot)
    normal = _make_message(msg_id=11, content="hello", author=user)
    channel = _FakeHistoryChannel([watermark_only, normal])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
            bot_user_id=99,
        )
    )

    assert len(context) == 1
    assert "hello" in context[0]["content"]


def test_channel_context_keeps_watermark_text_in_user_messages() -> None:
    user = _make_author(id=1, name="neo", display_name="Neo")
    message = _make_message(
        msg_id=10,
        content="what does -# -eva mean?",
        author=user,
    )
    channel = _FakeHistoryChannel([message])

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=5,
            bot_user_id=99,
        )
    )

    assert len(context) == 1
    assert "-# -eva" in context[0]["content"]


def test_ranked_context_prioritizes_reply_chain_and_fetches_ancestors() -> None:
    requester = _make_author(id=1, name="requester", display_name="Requester")
    other = _make_author(id=2, name="other", display_name="Other")
    parent = _make_message(
        msg_id=1,
        content="parent outside the history window",
        author=other,
        created_at=datetime(2026, 1, 1, 11, 57),
        reference=SimpleNamespace(message_id=2),
    )
    ancestor = _make_message(
        msg_id=2,
        content="ancestor outside the history window",
        author=other,
        created_at=datetime(2026, 1, 1, 11, 56),
    )
    current = _make_message(
        msg_id=99,
        content="eva current request",
        author=requester,
        created_at=datetime(2026, 1, 1, 12, 0),
        reference=SimpleNamespace(message_id=1),
    )
    unrelated = _make_message(
        msg_id=3,
        content="unrelated ambient message",
        author=other,
        created_at=datetime(2026, 1, 1, 11, 59),
    )
    channel = _FakeHistoryChannel(
        [current, unrelated],
        fetched_messages={1: parent, 2: ancestor},
    )

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=2,
            exclude_message_id=99,
            requester_user_id=1,
            reply_message_id=1,
        )
    )

    contents = [str(message["content"]) for message in context]
    assert any("ancestor outside the history window" in content for content in contents)
    assert any("parent outside the history window" in content for content in contents)
    assert all("eva current request" not in content for content in contents)
    assert contents == sorted(
        contents,
        key=lambda content: ("ancestor" not in content, "parent" not in content),
    )
    assert "[PRIMARY_REPLY_CHAIN]" in "\n".join(contents)


def test_ranked_context_caps_requester_eva_and_ambient_turns() -> None:
    requester = _make_author(id=1, name="requester", display_name="Requester")
    eva = _make_author(id=99, name="eva", display_name="Eva")
    other = _make_author(id=2, name="other", display_name="Other")
    messages: list[Any] = []
    for index in range(1, 9):
        messages.append(
            _make_message(
                msg_id=index,
                content=f"requester turn {index}",
                author=requester,
                created_at=datetime(2026, 1, 1, 12, index),
            )
        )
    for index in range(9, 13):
        messages.append(
            _make_message(
                msg_id=index,
                content=f"eva turn {index}",
                author=eva,
                created_at=datetime(2026, 1, 1, 12, index),
            )
        )
    for index in range(13, 20):
        messages.append(
            _make_message(
                msg_id=index,
                content=f"ambient turn {index}",
                author=other,
                created_at=datetime(2026, 1, 1, 12, index),
            )
        )
    channel = _FakeHistoryChannel(list(reversed(messages)))

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=30,
            requester_user_id=1,
            bot_user_id=99,
            account_mode="standalone",
        )
    )

    contents = [str(message["content"]) for message in context]
    requester_eva = [
        content
        for content in contents
        if "[REQUESTER_EVA_CONTEXT]" in content
    ]
    ambient = [content for content in contents if "[AMBIENT_CONTEXT]" in content]
    assert len(requester_eva) == 6
    assert len(ambient) == 4
    assert all("requester turn" not in content for content in ambient)
    assert all("eva turn" not in content for content in ambient)
    assert contents == sorted(
        contents,
        key=lambda content: int(content.split("message_id:", 1)[1].split("]", 1)[0]),
    )


def test_ranked_context_total_cap_preserves_reply_chain_before_ambient() -> None:
    requester = _make_author(id=1, name="requester", display_name="Requester")
    other = _make_author(id=2, name="other", display_name="Other")
    parent = _make_message(
        msg_id=1,
        content="parent " + ("p" * 700),
        author=other,
        created_at=datetime(2026, 1, 1, 11, 58),
        reference=SimpleNamespace(message_id=2),
    )
    ancestor = _make_message(
        msg_id=2,
        content="ancestor " + ("a" * 700),
        author=other,
        created_at=datetime(2026, 1, 1, 11, 57),
    )
    requester_turn = _make_message(
        msg_id=3,
        content="requester turn " + ("r" * 700),
        author=requester,
        created_at=datetime(2026, 1, 1, 11, 59),
    )
    ambient = _make_message(
        msg_id=4,
        content="ambient turn " + ("x" * 700),
        author=other,
        created_at=datetime(2026, 1, 1, 11, 59, 30),
    )
    current = _make_message(
        msg_id=99,
        content="latest request",
        author=requester,
        created_at=datetime(2026, 1, 1, 12, 0),
        reference=SimpleNamespace(message_id=1),
    )
    channel = _FakeHistoryChannel(
        [current, ambient, requester_turn],
        fetched_messages={1: parent, 2: ancestor},
    )

    context = asyncio.run(
        fetch_channel_context(
            cast(discord.abc.Messageable, channel),
            limit=4,
            exclude_message_id=99,
            requester_user_id=1,
            reply_message_id=1,
            max_message_chars=500,
            max_total_chars=900,
        )
    )

    joined = "\n".join(str(message["content"]) for message in context)
    assert "parent" in joined
    assert "ancestor" in joined
    assert "ambient turn" not in joined
    assert "requester turn" not in joined
    assert len(joined) <= 900
