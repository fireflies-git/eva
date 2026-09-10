from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import discord

from eva.ai.client import ChatCompletionClient
from eva.ai.orchestrator import ReplyGenerationService, ResponseGenerationResult
from eva.ai.respond import ResponseService
from eva.ai.schemas import VisionImage
from eva.discord.vision import remember_message_images, resolve_vision_selection
from eva.state.vision_images import VisionImageStore


class _FakeAttachment:
    def __init__(
        self,
        filename: str,
        data: bytes,
        *,
        content_type: str | None = None,
        size: int | None = None,
        error: Exception | None = None,
    ) -> None:
        self.filename = filename
        self.content_type = content_type
        self.size = len(data) if size is None else size
        self._data = data
        self._error = error

    async def read(self) -> bytes:
        if self._error is not None:
            raise self._error
        return self._data


class _FakeChatClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "vision reply"


class _FailingResponseService:
    async def generate_reply(self, **kwargs: object) -> object:
        raise AssertionError("the response model should not run without an image")


class _RecordingResponseService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs: object) -> ResponseGenerationResult:
        self.calls.append(kwargs)
        return ResponseGenerationResult("reply")


class _AllowingTOSService:
    async def check_tos_violation(self, text: str) -> bool:
        return False


def _vision_image(
    message_id: int,
    filename: str = "photo.png",
    data: bytes = b"image-bytes",
) -> VisionImage:
    return VisionImage(
        message_id=message_id,
        filename=filename,
        mime_type="image/png",
        data=data,
    )


def test_vision_store_keeps_recent_groups_and_clears_channels() -> None:
    store = VisionImageStore(max_groups_per_channel=1, max_bytes=10)
    first = _vision_image(1, data=b"1234")
    second = _vision_image(2, data=b"5678")

    store.put(10, 1, [first])
    store.put(10, 2, [second])

    assert store.get_for_message(10, 1) == ()
    assert store.get_for_message(10, 2) == (second,)
    assert store.get_latest(10) == (second,)

    store.clear(10)

    assert store.get_latest(10) == ()


def test_vision_store_evicts_oldest_groups_when_global_budget_is_reached() -> None:
    store = VisionImageStore(max_groups_per_channel=4, max_bytes=7)
    first = _vision_image(1, data=b"1234")
    second = _vision_image(2, data=b"5678")

    store.put(10, 1, [first])
    store.put(11, 2, [second])

    assert store.get_for_message(10, 1) == ()
    assert store.get_for_message(11, 2) == (second,)


def test_vision_store_enforces_image_and_request_limits() -> None:
    store = VisionImageStore()
    image_data = b"x" * 8_000_000
    images = [_vision_image(index, filename=f"{index}.png", data=image_data) for index in range(5)]
    images.append(_vision_image(99, filename="small.png", data=b"small"))

    store.put(10, 1, images)
    stored = store.get_for_message(10, 1)

    assert len(stored) == 3
    assert [image.filename for image in stored] == ["0.png", "1.png", "2.png"]


def test_vision_store_limits_each_message_to_four_images() -> None:
    store = VisionImageStore()
    images = [_vision_image(index, filename=f"{index}.png", data=b"x") for index in range(5)]

    store.put(10, 1, images)

    assert len(store.get_for_message(10, 1)) == 4


def test_attachment_capture_accepts_supported_signatures() -> None:
    attachments = [
        _FakeAttachment("photo.png", b"\x89PNG\r\n\x1a\nrest"),
        _FakeAttachment("photo.jpg", b"\xff\xd8\xffrest"),
        _FakeAttachment("photo.gif", b"GIF89arest"),
        _FakeAttachment("photo.webp", b"RIFFxxxxWEBPrest"),
    ]
    message = cast(
        discord.Message,
        SimpleNamespace(id=20, attachments=attachments),
    )
    store = VisionImageStore()

    asyncio.run(remember_message_images(message, channel_id=10, store=store))

    assert [image.mime_type for image in store.get_latest(10)] == [
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    ]


def test_attachment_capture_uses_bytes_for_unknown_attachment_metadata() -> None:
    message = cast(
        discord.Message,
        SimpleNamespace(
            id=22,
            attachments=[
                _FakeAttachment(
                    "download",
                    b"\x89PNG\r\n\x1a\nrest",
                    content_type="application/octet-stream",
                )
            ],
        ),
    )
    store = VisionImageStore()

    asyncio.run(remember_message_images(message, channel_id=10, store=store))

    assert store.get_latest(10)[0].mime_type == "image/png"


def test_attachment_capture_skips_invalid_oversized_and_failed_images() -> None:
    attachments = [
        _FakeAttachment("empty.png", b""),
        _FakeAttachment("bad.png", b"not-an-image"),
        _FakeAttachment("large.png", b"data", size=8_000_001),
        _FakeAttachment("failed.png", b"data", error=OSError("download failed")),
    ]
    message = cast(
        discord.Message,
        SimpleNamespace(id=21, attachments=attachments),
    )
    store = VisionImageStore()

    asyncio.run(remember_message_images(message, channel_id=10, store=store))

    assert store.get_latest(10) == ()


def test_vision_selection_prefers_current_then_reply_then_latest() -> None:
    store = VisionImageStore()
    latest = _vision_image(1, filename="latest.png")
    reply = _vision_image(2, filename="reply.png")
    current = _vision_image(3, filename="current.png")
    store.put(10, 1, [latest])
    store.put(10, 2, [reply])

    reply_message = cast(
        discord.Message,
        SimpleNamespace(
            id=4,
            attachments=[],
            reference=SimpleNamespace(message_id=2),
        ),
    )
    reply_selection = resolve_vision_selection(
        reply_message,
        channel_id=10,
        user_query="describe this",
        reply_context="[message_id:2] @user: [no text] | attached: reply.png",
        store=store,
    )
    assert reply_selection.images == (reply,)

    store.put(10, 4, [current])
    current_selection = resolve_vision_selection(
        reply_message,
        channel_id=10,
        user_query="describe this",
        reply_context="[message_id:2] @user: [no text] | attached: reply.png",
        store=store,
    )
    assert current_selection.images == (current,)


def test_vision_selection_does_not_fall_back_from_unavailable_current_image() -> None:
    store = VisionImageStore()
    store.put(10, 1, [_vision_image(1, filename="older.png")])
    message = cast(
        discord.Message,
        SimpleNamespace(
            id=2,
            attachments=[_FakeAttachment("current.png", b"not-an-image")],
            reference=None,
        ),
    )

    selection = resolve_vision_selection(
        message,
        channel_id=10,
        user_query="describe this image",
        reply_context=None,
        store=store,
    )

    assert selection.requested is True
    assert selection.images == ()


def test_vision_selection_blocks_fallback_for_unavailable_referenced_image() -> None:
    store = VisionImageStore()
    store.put(10, 1, [_vision_image(1, filename="older.png")])
    message = cast(
        discord.Message,
        SimpleNamespace(
            id=2,
            attachments=[],
            reference=SimpleNamespace(
                message_id=3,
                resolved=SimpleNamespace(
                    attachments=[_FakeAttachment("referenced.png", b"not-an-image")]
                ),
            ),
        ),
    )

    selection = resolve_vision_selection(
        message,
        channel_id=10,
        user_query="describe this image",
        reply_context=None,
        store=store,
    )

    assert selection.requested is True
    assert selection.images == ()


def test_response_service_adds_images_only_to_final_user_message() -> None:
    client = _FakeChatClient()
    service = ResponseService(
        client=cast(ChatCompletionClient, client),
        model_name="deepseek-flash",
    )

    asyncio.run(
        service.generate_reply(
            system_prompt="system prompt",
            context_messages=[{"role": "user", "content": "context"}],
            history_messages=[],
            user_message="describe this image",
            reply_context=None,
            requester_context=None,
            vision_images=[_vision_image(3, data=b"abc")],
        )
    )

    messages = cast(list[dict[str, Any]], client.calls[0]["messages"])
    assert isinstance(messages[0]["content"], str)
    assert isinstance(messages[1]["content"], str)
    user_content = messages[2]["content"]
    assert isinstance(user_content, list)
    assert user_content[0] == {"type": "text", "text": "describe this image"}
    assert user_content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,YWJj"},
    }


def test_response_service_keeps_normal_requests_text_only() -> None:
    client = _FakeChatClient()
    service = ResponseService(
        client=cast(ChatCompletionClient, client),
        model_name="deepseek-flash",
    )

    asyncio.run(
        service.generate_reply(
            system_prompt="system prompt",
            context_messages=[],
            history_messages=[],
            user_message="hello",
            reply_context=None,
            requester_context=None,
        )
    )

    messages = cast(list[dict[str, Any]], client.calls[0]["messages"])
    assert isinstance(messages[-1]["content"], str)
    assert "image_url" not in str(messages)


def test_reply_generation_reports_missing_requested_image_without_response_call() -> None:
    service = ReplyGenerationService(
        response_service=cast(Any, _FailingResponseService()),
        tos_check_service=_AllowingTOSService(),
    )

    reply = asyncio.run(
        service.generate_reply(
            channel=cast(discord.abc.Messageable, SimpleNamespace()),
            client=cast(discord.Client, SimpleNamespace()),
            context_messages=[],
            history_messages=[],
            user_message="describe this image",
            reply_context=None,
            vision_requested=True,
        )
    )

    assert "supported image" in reply.content


def test_reply_generation_drops_images_for_non_visual_requests() -> None:
    response_service = _RecordingResponseService()
    service = ReplyGenerationService(
        response_service=cast(Any, response_service),
        tos_check_service=_AllowingTOSService(),
    )

    asyncio.run(
        service.generate_reply(
            channel=cast(discord.abc.Messageable, SimpleNamespace(guild=None, name="DM")),
            client=cast(discord.Client, SimpleNamespace(user=None)),
            context_messages=[],
            history_messages=[],
            user_message="hello",
            reply_context=None,
            vision_images=[_vision_image(3)],
            vision_requested=False,
        )
    )

    assert response_service.calls[0]["vision_images"] == ()
