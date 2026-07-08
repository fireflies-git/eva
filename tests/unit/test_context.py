from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import cast

import discord

from eva.discord.context import fetch_channel_context, fetch_reply_context


class FakeHistoryChannel:
    def __init__(self, messages: list[object]) -> None:
        self._messages = messages

    async def history(self, *, limit: int, oldest_first: bool) -> object:
        for message in self._messages[:limit]:
            yield message


class FakeReplyChannel:
    def __init__(self, message: object) -> None:
        self._message = message

    async def fetch_message(self, message_id: int) -> object:
        return self._message


def test_fetch_channel_context_includes_user_and_mentions() -> None:
    mention = SimpleNamespace(id=2, name="trinity", display_name="Trinity")
    author = SimpleNamespace(id=1, name="neo", display_name="Neo")
    message = SimpleNamespace(
        id=10,
        content="hello there",
        created_at=datetime(2026, 1, 1, 12, 30),
        author=author,
        mentions=[mention],
    )
    channel = FakeHistoryChannel([message])

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
    reply_author = SimpleNamespace(id=7, name="neo", display_name="Neo")
    referenced_message = SimpleNamespace(
        content="previous message", author=reply_author, mentions=[]
    )
    channel = FakeReplyChannel(referenced_message)
    message = SimpleNamespace(
        reference=SimpleNamespace(message_id=123),
        channel=channel,
    )

    reply_context = asyncio.run(fetch_reply_context(cast(discord.Message, message)))

    assert reply_context is not None
    assert "username=neo" in reply_context
    assert "pronouns=" not in reply_context
    assert "previous message" in reply_context
