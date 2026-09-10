from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import discord

import eva.discord.handlers as handlers
from eva.ai.client import ChatCompletionClient
from eva.ai.orchestrator import ReplyGenerationService, ReplyOutput
from eva.ai.respond import ResponseService
from eva.ai.schemas import VisionImage
from eva.config import Settings
from eva.discord.handlers import SelfbotMessageHandler
from eva.state import (
    ChannelHistoryStore,
    RateLimiter,
    ReminderStore,
    TrackedMessageStore,
    UserMemoryStore,
    VisionImageStore,
    WhitelistStore,
)


class _Attachment:
    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self.content_type = None
        self.size = len(data)
        self._data = data

    async def read(self) -> bytes:
        return self._data


class _Typing:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class _Channel:
    def __init__(self, *, channel_id: int = 10) -> None:
        self.id = channel_id
        self.name = "vision-tests"
        self.guild = SimpleNamespace(
            name="test-server", owner=SimpleNamespace(display_name="owner")
        )
        self.messages: dict[int, object] = {}

    def typing(self) -> _Typing:
        return _Typing()

    async def fetch_message(self, message_id: int) -> object:
        return self.messages[message_id]


class _CapturingReplyService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs: object) -> ReplyOutput:
        self.calls.append(kwargs)
        return ReplyOutput(content="captured reply", attachments=[])


class _AllowingTOSService:
    async def check_tos_violation(self, text: str) -> bool:
        return False


class _RecordingChatClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.messages = [
            dict(message) for message in cast(list[dict[str, object]], kwargs["messages"])
        ]
        return "model reply"


class _FailingResponseService:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_reply(self, **kwargs: object) -> object:
        self.calls += 1
        raise AssertionError("response model should not run without a usable image")


def _settings(tmp_path: Path, *, account_mode: str) -> Settings:
    return Settings(
        discord_token="token",
        api_key="key",
        image_api_key=None,
        api_base_url="https://example.com/v1",
        account_mode=account_mode,
        model_name="deepseek-flash",
        split_model_name="deepseek-flash",
        tos_model_name="deepseek-flash",
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
        terminal_enabled=False,
        terminal_autonomous_enabled=False,
        terminal_workdir=str(tmp_path),
        terminal_shell="/bin/sh",
        terminal_timeout_seconds=15.0,
        terminal_max_output_chars=6000,
        rate_limit_max_requests=20,
        rate_limit_window_seconds=60.0,
        state_dir=str(tmp_path),
        playwright_enabled=False,
        playwright_timeout_seconds=30.0,
        playwright_max_content_chars=10000,
        nopecha_enabled=False,
        nopecha_api_key=None,
        context7_api_key=None,
    )


def _handler(
    tmp_path: Path,
    reply_service: object,
    *,
    vision_store: VisionImageStore | None = None,
    account_mode: str = "assistant",
) -> SelfbotMessageHandler:
    handler = SelfbotMessageHandler(
        settings=_settings(tmp_path, account_mode=account_mode),
        reply_generation_service=cast(ReplyGenerationService, reply_service),
        history_store=ChannelHistoryStore(),
        tracked_messages=TrackedMessageStore(path=tmp_path / "tracked.json"),
        whitelist=WhitelistStore(tmp_path / "whitelist.json"),
        user_memory=UserMemoryStore(path=tmp_path / "user_memory.json"),
        reminder_store=ReminderStore(path=tmp_path / "reminders.json"),
        rate_limiter=RateLimiter(max_requests=1_000_000, window_seconds=1.0),
        summarization_service=None,
        terminal_service=None,
        download_service=None,
        vision_store=vision_store,
    )
    if account_mode == "assistant":
        handler._whitelist.add(2)
    return handler


def _client() -> discord.Client:
    return cast(
        discord.Client,
        SimpleNamespace(user=SimpleNamespace(id=1, name="eva", display_name="Eva")),
    )


def _message(
    channel: _Channel,
    *,
    message_id: int,
    content: str,
    attachments: list[_Attachment] | None = None,
    reference: object | None = None,
    author_id: int = 2,
) -> discord.Message:
    message = cast(
        discord.Message,
        SimpleNamespace(
            id=message_id,
            content=content,
            author=SimpleNamespace(id=author_id, display_name="user"),
            channel=channel,
            reference=reference,
            attachments=attachments or [],
            mentions=[],
            edited_at=None,
        ),
    )
    channel.messages[message_id] = message
    return message


def _patch_delivery(monkeypatch: Any, delivered: list[str]) -> None:
    async def fake_deliver_reply_response(**kwargs: object) -> object:
        delivered.append(cast(str, kwargs["reply_content"]))
        return SimpleNamespace(
            primary_delivered=True,
            tracked_message_ids=[],
            had_continuation_failures=False,
        )

    monkeypatch.setattr(handlers, "deliver_reply_response", fake_deliver_reply_response)


def test_handler_sends_current_attachment_for_explicit_visual_request(
    monkeypatch, tmp_path
) -> None:
    response_service = _CapturingReplyService()
    handler = _handler(tmp_path, response_service)
    delivered: list[str] = []
    _patch_delivery(monkeypatch, delivered)
    channel = _Channel()
    message = _message(
        channel,
        message_id=1,
        content="eva describe this screenshot",
        attachments=[_Attachment("screen.png", b"\x89PNG\r\n\x1a\nbytes")],
    )

    asyncio.run(handler.on_message(_client(), message))

    assert delivered == ["captured reply"]
    assert len(response_service.calls) == 1
    assert response_service.calls[0]["vision_requested"] is True
    images = cast(tuple[VisionImage, ...], response_service.calls[0]["vision_images"])
    assert [image.filename for image in images] == ["screen.png"]


def test_handler_uses_referenced_and_latest_cached_images_for_followups(
    monkeypatch, tmp_path
) -> None:
    response_service = _CapturingReplyService()
    handler = _handler(tmp_path, response_service)
    delivered: list[str] = []
    _patch_delivery(monkeypatch, delivered)
    channel = _Channel()
    original = _message(
        channel,
        message_id=1,
        content="here is the image",
        attachments=[_Attachment("photo.jpg", b"\xff\xd8\xffbytes")],
    )
    asyncio.run(handler.on_message(_client(), original))

    referenced_followup = _message(
        channel,
        message_id=2,
        content="eva describe this",
        reference=SimpleNamespace(message_id=original.id),
    )
    latest_followup = _message(
        channel,
        message_id=3,
        content="eva describe this",
    )
    asyncio.run(handler.on_message(_client(), referenced_followup))
    asyncio.run(handler.on_message(_client(), latest_followup))

    assert len(response_service.calls) == 2
    for call in response_service.calls:
        images = cast(tuple[VisionImage, ...], call["vision_images"])
        assert [image.filename for image in images] == ["photo.jpg"]
        assert call["vision_requested"] is True


def test_handler_keeps_normal_attachment_requests_text_only(monkeypatch, tmp_path) -> None:
    response_service = _CapturingReplyService()
    handler = _handler(tmp_path, response_service)
    delivered: list[str] = []
    _patch_delivery(monkeypatch, delivered)
    channel = _Channel()
    message = _message(
        channel,
        message_id=1,
        content="eva hello",
        attachments=[_Attachment("photo.png", b"\x89PNG\r\n\x1a\nbytes")],
    )

    asyncio.run(handler.on_message(_client(), message))

    assert len(response_service.calls) == 1
    assert response_service.calls[0]["vision_requested"] is False
    assert response_service.calls[0]["vision_images"] == ()


def test_handler_warns_without_calling_response_model_when_image_is_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    failing_response = _FailingResponseService()
    reply_service = ReplyGenerationService(
        response_service=cast(Any, failing_response),
        tos_check_service=_AllowingTOSService(),
        account_mode="assistant",
    )
    handler = _handler(tmp_path, reply_service)
    delivered: list[str] = []
    _patch_delivery(monkeypatch, delivered)
    channel = _Channel()
    message = _message(channel, message_id=1, content="eva describe this screenshot")

    asyncio.run(handler.on_message(_client(), message))

    assert failing_response.calls == 0
    assert len(delivered) == 1
    assert "supported image" in delivered[0]


def test_clear_command_removes_channel_vision_cache(monkeypatch, tmp_path) -> None:
    store = VisionImageStore()
    store.put(
        10,
        1,
        [VisionImage(message_id=1, filename="photo.png", mime_type="image/png", data=b"bytes")],
    )
    store.put(
        11,
        2,
        [VisionImage(message_id=2, filename="other.png", mime_type="image/png", data=b"bytes")],
    )
    handler = _handler(
        tmp_path,
        _CapturingReplyService(),
        vision_store=store,
        account_mode="standalone",
    )
    handler._history_store.append_exchange(10, "old user", "old reply")
    handler._history_store.append_exchange(11, "keep user", "keep reply")
    delivered: list[str] = []
    _patch_delivery(monkeypatch, delivered)
    channel = _Channel(channel_id=10)
    message = _message(channel, message_id=3, content="eva clear", author_id=1)

    asyncio.run(handler.on_message(_client(), message))

    assert delivered == ["✔ Cleared memory for this channel."]
    assert store.get_latest(10) == ()
    assert store.get_latest(11)
    assert handler._history_store.get(10) == []
    assert handler._history_store.get(11)


def test_handler_builds_deepseek_multimodal_payload_end_to_end(monkeypatch, tmp_path) -> None:
    client = _RecordingChatClient()
    response_service = ResponseService(
        client=cast(ChatCompletionClient, client),
        model_name="deepseek-flash",
    )
    reply_service = ReplyGenerationService(
        response_service=response_service,
        tos_check_service=_AllowingTOSService(),
        account_mode="assistant",
    )
    handler = _handler(tmp_path, reply_service)
    delivered: list[str] = []
    _patch_delivery(monkeypatch, delivered)
    channel = _Channel()
    message = _message(
        channel,
        message_id=1,
        content="eva read this image",
        attachments=[_Attachment("photo.webp", b"RIFFxxxxWEBPbytes")],
    )

    asyncio.run(handler.on_message(_client(), message))

    assert delivered == ["model reply\n-# -eva"]
    assert client.messages[0]["role"] == "system"
    assert isinstance(client.messages[-1]["content"], list)
    user_content = cast(list[dict[str, object]], client.messages[-1]["content"])
    assert user_content[0]["type"] == "text"
    assert cast(str, user_content[0]["text"]).endswith("read this image")
    assert user_content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/webp;base64,UklGRnh4eHhXRUJQYnl0ZXM="},
    }
    assert all(isinstance(message["content"], str) for message in client.messages[:-1])
