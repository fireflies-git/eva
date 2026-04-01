import asyncio
from types import SimpleNamespace
from typing import cast

import discord
import pytest

import eva.discord.handlers as handlers
from eva.ai import ReplyGenerationService, ResponseGenerationResult, ResponseSplitService
from eva.config import Settings
from eva.discord.handlers import SelfbotMessageHandler, TriggerDecision
from eva.downloads import DownloadService
from eva.state import ChannelHistoryStore, ChannelResponseStore, TrackedMessageStore, WhitelistStore
from eva.terminal import TerminalService


class DummyResponseService:
    async def generate_reply(self, **kwargs: object) -> ResponseGenerationResult:
        return ResponseGenerationResult("unused")


class DummyTOSCheckService:
    async def check_tos_violation(self, text: str) -> bool:
        return False


class DummySplitService:
    async def split_reply(
        self,
        *,
        reply_content: str,
        first_limit: int,
        continuation_limit: int,
    ) -> list[str] | None:
        return [reply_content[:first_limit]]


class DummyChannel:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bool]] = []
        self._next_id = 100

    async def send(self, *, content: str, suppress_embeds: bool) -> object:
        self.sent.append((content, suppress_embeds))
        self._next_id += 1
        return type("SentMessage", (), {"id": self._next_id})()


class DummySplitClient:
    async def chat_completion(self, **kwargs: object) -> str:
        return '{"messages":["unused"]}'


def _build_handler(tmp_path, *, account_mode: str = "standalone") -> SelfbotMessageHandler:
    settings = Settings(
        discord_token="token",
        api_key="key",
        serper_api_key=None,
        image_api_key=None,
        api_base_url="https://example.com/v1",
        account_mode=account_mode,
        model_name="openai-gpt-oss-120b",
        split_model_name="llama3.3-70b-instruct",
        trigger_prefix="eva ",
        max_history_messages=20,
        response_context_messages=25,
        request_timeout_seconds=30.0,
        min_loading_seconds=1.0,
        followup_delay_min_seconds=0.75,
        followup_delay_max_seconds=1.5,
        image_api_base_url="https://images.example.com/v1",
        image_model_name="sonar",
        image_language="en-US",
        image_incognito=True,
        terminal_enabled=True,
        terminal_autonomous_enabled=True,
        terminal_workdir="/app",
        terminal_shell="/bin/sh",
        terminal_timeout_seconds=15.0,
        terminal_max_output_chars=6000,
    )
    reply_generation_service = ReplyGenerationService(
        account_mode=settings.account_mode,
        response_service=DummyResponseService(),
        search_service=None,
        search_response_service=None,
        tos_check_service=DummyTOSCheckService(),
    )
    response_split_service = ResponseSplitService(
        client=DummySplitClient(),
        model_name=settings.split_model_name,
    )
    return SelfbotMessageHandler(
        settings=settings,
        reply_generation_service=reply_generation_service,
        response_split_service=response_split_service,
        history_store=ChannelHistoryStore(),
        response_store=ChannelResponseStore(),
        tracked_messages=TrackedMessageStore(),
        whitelist=WhitelistStore(tmp_path / "whitelist.json"),
        terminal_service=None,
        download_service=None,
    )


def test_calculate_followup_delay_scales_with_length(monkeypatch, tmp_path) -> None:
    handler = _build_handler(tmp_path)
    monkeypatch.setattr("eva.discord.handlers.random.uniform", lambda low, high: 0.0)

    short_delay = handler._calculate_followup_delay_seconds("short")
    long_delay = handler._calculate_followup_delay_seconds("x" * 1200)

    assert short_delay == pytest.approx(0.75 + (0.75 * (5 / 1200)))
    assert long_delay == pytest.approx(1.5)


def test_send_followup_messages_waits_and_tracks_sent_ids(monkeypatch, tmp_path) -> None:
    handler = _build_handler(tmp_path)
    channel = DummyChannel()
    sleeps: list[float] = []

    monkeypatch.setattr("eva.discord.handlers.random.uniform", lambda low, high: 0.0)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("eva.discord.handlers.asyncio.sleep", fake_sleep)

    asyncio.run(
        handler._send_followup_messages(
            cast(discord.abc.Messageable, channel),
            ["short", "x" * 1200],
        )
    )

    assert sleeps == [
        pytest.approx(0.75 + (0.75 * (5 / 1200))),
        pytest.approx(1.5),
    ]
    assert channel.sent == [("short", True), ("x" * 1200, True)]
    assert handler._tracked_messages.contains(101)
    assert handler._tracked_messages.contains(102)


def test_standalone_dm_trigger_accepts_any_non_empty_message(tmp_path) -> None:
    handler = _build_handler(tmp_path)
    message = cast(discord.Message, SimpleNamespace(channel=SimpleNamespace(guild=None)))

    decision = handler._decide_standalone_trigger(
        message=message,
        content="help me with this",
        is_reply_trigger=False,
        mention_user_id=123,
    )

    assert decision == TriggerDecision(should_process=True, user_query="help me with this")


def test_standalone_server_trigger_uses_mentions_replies_and_prefix(tmp_path) -> None:
    handler = _build_handler(tmp_path)
    server_channel = SimpleNamespace(guild=SimpleNamespace(id=1))

    mention_message = cast(
        discord.Message,
        SimpleNamespace(channel=server_channel, raw_mentions=[123], content="hey <@123> help me"),
    )
    mention_decision = handler._decide_standalone_trigger(
        message=mention_message,
        content="hey <@123> help me",
        is_reply_trigger=False,
        mention_user_id=123,
    )

    reply_message = cast(discord.Message, SimpleNamespace(channel=server_channel))
    reply_decision = handler._decide_standalone_trigger(
        message=reply_message,
        content="continue",
        is_reply_trigger=True,
        mention_user_id=123,
    )

    prefix_decision = handler._decide_standalone_trigger(
        message=reply_message,
        content="eva summarize this",
        is_reply_trigger=False,
        mention_user_id=123,
    )

    chatter_decision = handler._decide_standalone_trigger(
        message=reply_message,
        content="random chatter",
        is_reply_trigger=False,
        mention_user_id=123,
    )

    assert mention_decision == TriggerDecision(should_process=True, user_query="hey help me")
    assert reply_decision == TriggerDecision(
        should_process=True,
        user_query="continue",
        is_reply_trigger=True,
    )
    assert prefix_decision == TriggerDecision(should_process=True, user_query="summarize this")
    assert chatter_decision == TriggerDecision(should_process=False)


def test_assistant_mode_skips_ai_split_planner(monkeypatch, tmp_path) -> None:
    handler = _build_handler(tmp_path, account_mode="assistant")

    async def fail_split_reply(**kwargs: object) -> list[str] | None:
        raise AssertionError("split planner should not run in assistant mode")

    monkeypatch.setattr(handler._response_split_service, "split_reply", fail_split_reply)

    chunks = asyncio.run(handler._build_plain_response_chunks("one message only"))

    assert chunks == ["one message only"]


def test_terminal_command_bypasses_ai_generation(monkeypatch, tmp_path) -> None:
    class FailingReplyGenerationService:
        async def generate_reply(self, **kwargs: object) -> object:
            raise AssertionError("AI generation should not run for terminal commands")

    settings = Settings(
        discord_token="token",
        api_key="key",
        serper_api_key=None,
        image_api_key=None,
        api_base_url="https://example.com/v1",
        account_mode="assistant",
        model_name="openai-gpt-oss-120b",
        split_model_name="llama3.3-70b-instruct",
        trigger_prefix="eva ",
        max_history_messages=20,
        response_context_messages=25,
        request_timeout_seconds=30.0,
        min_loading_seconds=0.0,
        followup_delay_min_seconds=0.75,
        followup_delay_max_seconds=1.5,
        image_api_base_url="https://images.example.com/v1",
        image_model_name="sonar",
        image_language="en-US",
        image_incognito=True,
        terminal_enabled=True,
        terminal_autonomous_enabled=True,
        terminal_workdir=str(tmp_path),
        terminal_shell="/bin/sh",
        terminal_timeout_seconds=5.0,
        terminal_max_output_chars=200,
    )
    terminal_service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )
    handler = SelfbotMessageHandler(
        settings=settings,
        reply_generation_service=cast(ReplyGenerationService, FailingReplyGenerationService()),
        history_store=ChannelHistoryStore(),
        response_store=ChannelResponseStore(),
        tracked_messages=TrackedMessageStore(),
        whitelist=WhitelistStore(tmp_path / "whitelist.json"),
        terminal_service=terminal_service,
        download_service=None,
    )

    delivered: list[str] = []

    async def fake_deliver_reply_response(**kwargs: object) -> object:
        delivered.append(cast(str, kwargs["reply_content"]))
        return SimpleNamespace(
            primary_delivered=True, tracked_message_ids=[], had_continuation_failures=False
        )

    monkeypatch.setattr(handlers, "deliver_reply_response", fake_deliver_reply_response)

    message = cast(
        discord.Message,
        SimpleNamespace(
            author=SimpleNamespace(id=218675193592283137, display_name="admin"),
            channel=SimpleNamespace(id=1),
            content="eva shell pwd",
            id=123,
            reference=None,
        ),
    )
    client = cast(discord.Client, SimpleNamespace(user=SimpleNamespace(id=1)))

    asyncio.run(handler.on_message(client, message))

    assert len(delivered) == 1
    assert "Terminal result" in delivered[0]


def test_download_command_bypasses_ai_generation(monkeypatch, tmp_path) -> None:
    class FailingReplyGenerationService:
        async def generate_reply(self, **kwargs: object) -> object:
            raise AssertionError("AI generation should not run for download commands")

    class FakeDownloadService:
        async def download_media(self, **kwargs: object) -> object:
            return type("Asset", (), {"filename": "clip.mp4", "data": b"video-bytes"})()

    settings = Settings(
        discord_token="token",
        api_key="key",
        serper_api_key=None,
        image_api_key=None,
        api_base_url="https://example.com/v1",
        account_mode="assistant",
        model_name="openai-gpt-oss-120b",
        split_model_name="llama3.3-70b-instruct",
        trigger_prefix="eva ",
        max_history_messages=20,
        response_context_messages=25,
        request_timeout_seconds=30.0,
        min_loading_seconds=0.0,
        followup_delay_min_seconds=0.75,
        followup_delay_max_seconds=1.5,
        image_api_base_url="https://images.example.com/v1",
        image_model_name="sonar",
        image_language="en-US",
        image_incognito=True,
        terminal_enabled=True,
        terminal_autonomous_enabled=True,
        terminal_workdir=str(tmp_path),
        terminal_shell="/bin/sh",
        terminal_timeout_seconds=5.0,
        terminal_max_output_chars=200,
    )
    whitelist = WhitelistStore(tmp_path / "whitelist.json")
    whitelist.add(2)
    handler = SelfbotMessageHandler(
        settings=settings,
        reply_generation_service=cast(ReplyGenerationService, FailingReplyGenerationService()),
        history_store=ChannelHistoryStore(),
        response_store=ChannelResponseStore(),
        tracked_messages=TrackedMessageStore(),
        whitelist=whitelist,
        terminal_service=None,
        download_service=cast(DownloadService, FakeDownloadService()),
    )

    delivered: list[tuple[str, list[tuple[str, bytes]] | None]] = []

    async def fake_deliver_reply_response(**kwargs: object) -> object:
        delivered.append(
            (
                cast(str, kwargs["reply_content"]),
                cast(list[tuple[str, bytes]] | None, kwargs.get("reply_attachments")),
            )
        )
        return SimpleNamespace(
            primary_delivered=True,
            tracked_message_ids=[],
            had_continuation_failures=False,
        )

    monkeypatch.setattr(handlers, "deliver_reply_response", fake_deliver_reply_response)

    class DummyTypingContext:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
            return None

    message = cast(
        discord.Message,
        SimpleNamespace(
            author=SimpleNamespace(id=2, display_name="friend"),
            channel=SimpleNamespace(id=1, typing=lambda: DummyTypingContext()),
            guild=SimpleNamespace(filesize_limit=8 * 1024 * 1024),
            content="eva dl https://example.com/video",
            id=123,
            reference=None,
        ),
    )
    client = cast(discord.Client, SimpleNamespace(user=SimpleNamespace(id=1)))

    asyncio.run(handler.on_message(client, message))

    assert delivered == [
        ("✔ Downloaded `clip.mp4`", [("clip.mp4", b"video-bytes")]),
    ]


def test_clear_command_clears_only_current_channel_memory(monkeypatch, tmp_path) -> None:
    handler = _build_handler(tmp_path, account_mode="assistant")
    handler._history_store.append_exchange(1, "hello", "hi")
    handler._history_store.append_exchange(2, "yo", "sup")
    handler._response_store.set(1, "resp-1")
    handler._response_store.set(2, "resp-2")

    delivered: list[str] = []

    async def fake_deliver_owner_response(**kwargs: object) -> object:
        delivered.append(cast(str, kwargs["reply_content"]))
        return SimpleNamespace(
            primary_delivered=True,
            tracked_message_ids=[],
            had_continuation_failures=False,
        )

    monkeypatch.setattr(handlers, "deliver_owner_response", fake_deliver_owner_response)

    message = cast(
        discord.Message,
        SimpleNamespace(
            author=SimpleNamespace(id=1, display_name="owner"),
            channel=SimpleNamespace(id=1),
            content="eva clear",
            id=123,
            reference=None,
        ),
    )
    client = cast(discord.Client, SimpleNamespace(user=SimpleNamespace(id=1)))

    asyncio.run(handler.on_message(client, message))

    assert delivered == ["✔ Cleared memory for this channel."]
    assert handler._history_store.get(1) == []
    assert handler._response_store.get(1) is None
    assert len(handler._history_store.get(2)) == 2
    assert handler._response_store.get(2) == "resp-2"
