from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import discord
import pytest

import eva.discord.handlers as handlers
from eva.discord.delivery import DeliveryResult
from eva.state import ChannelHistoryStore, TrackedMessageStore, WhitelistStore


class StubReplyGenerationService:
    async def generate_reply(self, **kwargs: object) -> str:
        return "generated reply"


class DummyTypingContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class DummyChannel:
    def __init__(self, channel_id: int) -> None:
        self.id = channel_id

    def typing(self) -> DummyTypingContext:
        return DummyTypingContext()


class DummyMessage:
    def __init__(self, *, author_id: int, channel_id: int, content: str) -> None:
        self.author = SimpleNamespace(id=author_id)
        self.channel = DummyChannel(channel_id)
        self.content = content
        self.id = 55
        self.reference = None


class DummyClient:
    def __init__(self, user_id: int) -> None:
        self.user = SimpleNamespace(id=user_id)


@pytest.mark.parametrize("is_owner", [True, False])
def test_handler_does_not_append_history_when_primary_delivery_fails(
    monkeypatch: pytest.MonkeyPatch,
    is_owner: bool,
) -> None:
    history_store = ChannelHistoryStore()
    tracked_messages = TrackedMessageStore()
    whitelist = WhitelistStore()

    owner_id = 1
    user_id = owner_id if is_owner else 2
    if not is_owner:
        whitelist.add(user_id)

    handler = handlers.SelfbotMessageHandler(
        settings=SimpleNamespace(
            trigger_prefix="eva ",
            response_context_messages=5,
            min_loading_seconds=0.0,
        ),
        reply_generation_service=StubReplyGenerationService(),
        history_store=history_store,
        tracked_messages=tracked_messages,
        whitelist=whitelist,
    )

    async def fake_context(
        channel: discord.abc.Messageable,
        *,
        limit: int,
        exclude_message_id: int | None = None,
    ) -> list[dict[str, str]]:
        return []

    async def fake_reply_context(message: discord.Message) -> str | None:
        return None

    async def fake_safe_edit(message: discord.Message, content: str) -> bool:
        return True

    async def fake_owner_delivery(**kwargs: object) -> DeliveryResult:
        return DeliveryResult(primary_delivered=False)

    async def fake_reply_delivery(**kwargs: object) -> DeliveryResult:
        return DeliveryResult(primary_delivered=False)

    monkeypatch.setattr(handlers, "fetch_channel_context", fake_context)
    monkeypatch.setattr(handlers, "fetch_reply_context", fake_reply_context)
    monkeypatch.setattr(handlers, "safe_edit", fake_safe_edit)
    monkeypatch.setattr(handlers, "deliver_owner_response", fake_owner_delivery)
    monkeypatch.setattr(handlers, "deliver_reply_response", fake_reply_delivery)

    content = "eva hello" if is_owner else "eva hi"
    message = DummyMessage(author_id=user_id, channel_id=99, content=content)
    client = DummyClient(user_id=owner_id)

    asyncio.run(
        handler.on_message(
            cast(discord.Client, client),
            cast(discord.Message, message),
        )
    )

    assert history_store.get(99) == []
