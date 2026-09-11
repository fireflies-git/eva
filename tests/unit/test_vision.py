from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast

import discord

from eva.ai.client import ChatCompletionClient, ChatCompletionOutput, ModelToolCall
from eva.ai.respond import ResponseService
from eva.ai.schemas import VisionImage
from eva.discord.vision import remember_message_images, resolve_vision_selection
from eva.state.vision_images import VisionImageStore
from eva.tools.vision_service import VisionInspectionTool


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


class _AgentVisionClient:
    def __init__(self, *, inspect_images: bool, max_inspection_calls: int = 1) -> None:
        self.inspect_images = inspect_images
        self.max_inspection_calls = max_inspection_calls
        self.tool_calls: list[dict[str, object]] = []
        self.vision_calls: list[dict[str, object]] = []

    async def chat_completion_with_tools(self, **kwargs: object) -> ChatCompletionOutput:
        snapshot = dict(kwargs)
        snapshot["messages"] = [
            dict(message) for message in cast(list[dict[str, object]], kwargs["messages"])
        ]
        self.tool_calls.append(snapshot)
        if len(self.tool_calls) <= self.max_inspection_calls and self.inspect_images:
            focus = (
                "read the visible text" if len(self.tool_calls) == 1 else "double-check the finding"
            )
            return ChatCompletionOutput(
                content=None,
                tool_calls=[
                    ModelToolCall(
                        id="vision-1",
                        name="inspect_attached_images",
                        arguments=f'{{"focus":"{focus}"}}',
                    )
                ],
            )
        return ChatCompletionOutput(content="final answer", tool_calls=[])

    async def chat_completion(self, **kwargs: object) -> str:
        self.vision_calls.append(kwargs)
        return "The image contains the requested visible text."


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
        reply_context="[message_id:2] @user: [no text] | attached: reply.png",
        store=store,
    )
    assert reply_selection.images == (reply,)
    assert reply_selection.has_image_context is True

    store.put(10, 4, [current])
    current_selection = resolve_vision_selection(
        reply_message,
        channel_id=10,
        reply_context="[message_id:2] @user: [no text] | attached: reply.png",
        store=store,
    )
    assert current_selection.images == (current,)

    latest_message = cast(
        discord.Message,
        SimpleNamespace(id=5, attachments=[], reference=None),
    )
    latest_selection = resolve_vision_selection(
        latest_message,
        channel_id=10,
        reply_context=None,
        store=store,
    )
    assert latest_selection.images == (current,)


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
        reply_context=None,
        store=store,
    )

    assert selection.has_image_context is True
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
        reply_context=None,
        store=store,
    )

    assert selection.has_image_context is True
    assert selection.images == ()


def test_vision_tool_performs_a_separate_base64_vision_pass() -> None:
    client = _AgentVisionClient(inspect_images=True)
    service = ResponseService(
        client=cast(ChatCompletionClient, client),
        model_name="deepseek-v4-flash-vision-exp",
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="system prompt",
            context_messages=[{"role": "user", "content": "context"}],
            history_messages=[],
            user_message="what does this say?",
            reply_context=None,
            requester_context=None,
            vision_images=[_vision_image(3, data=b"abc")],
            vision_context_available=True,
        )
    )

    assert reply.content == "final answer"
    assert len(client.tool_calls) == 2
    assert len(client.vision_calls) == 1

    initial_messages = cast(list[dict[str, Any]], client.tool_calls[0]["messages"])
    assert isinstance(initial_messages[-1]["content"], str)
    assert "image_url" not in str(initial_messages)

    vision_messages = cast(list[dict[str, Any]], client.vision_calls[0]["messages"])
    assert vision_messages[0]["role"] == "system"
    assert isinstance(vision_messages[0]["content"], str)
    vision_content = vision_messages[1]["content"]
    assert isinstance(vision_content, list)
    assert vision_content[0] == {
        "type": "text",
        "text": "User request: what does this say?\n"
        "Inspection focus: read the visible text\n"
        "Inspect the attached image(s) and return only the findings the parent assistant "
        "needs to answer the user.",
    }
    assert vision_content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,YWJj"},
    }

    final_messages = cast(list[dict[str, Any]], client.tool_calls[1]["messages"])
    assert any(
        message.get("role") == "tool" and "Image inspection findings" in str(message.get("content"))
        for message in final_messages
    )
    assert "image_url" not in str(final_messages)


def test_response_service_does_not_inspect_images_when_agent_declines_tool() -> None:
    client = _AgentVisionClient(inspect_images=False)
    service = ResponseService(
        client=cast(ChatCompletionClient, client),
        model_name="deepseek-v4-flash-vision-exp",
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="system prompt",
            context_messages=[],
            history_messages=[],
            user_message="hello",
            reply_context=None,
            requester_context=None,
            vision_images=[_vision_image(3, data=b"abc")],
            vision_context_available=True,
        )
    )

    assert reply.content == "final answer"
    assert len(client.tool_calls) == 1
    assert client.vision_calls == []
    tool_definitions = cast(list[dict[str, Any]], client.tool_calls[0]["tools"])
    assert tool_definitions[0]["function"]["name"] == "inspect_attached_images"


def test_response_service_allows_multiple_agent_passthrough_rounds() -> None:
    client = _AgentVisionClient(inspect_images=True, max_inspection_calls=2)
    service = ResponseService(
        client=cast(ChatCompletionClient, client),
        model_name="deepseek-v4-flash-vision-exp",
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="system prompt",
            context_messages=[],
            history_messages=[],
            user_message="compare the details in this image",
            reply_context=None,
            requester_context=None,
            vision_images=[_vision_image(3, data=b"abc")],
            vision_context_available=True,
        )
    )

    assert reply.content == "final answer"
    assert len(client.tool_calls) == 3
    assert len(client.vision_calls) == 2


def test_vision_tool_reports_unavailable_image_bytes_without_model_call() -> None:
    client = _FakeChatClient()
    tool = VisionInspectionTool(
        client=cast(ChatCompletionClient, client),
        model_name="deepseek-v4-flash-vision-exp",
        user_request="what is in this?",
        images=[],
        image_context_available=True,
    )

    result = asyncio.run(tool.run_autonomous_tool("{}"))

    assert "no readable supported image bytes" in result
    assert client.calls == []


def test_vision_tool_rejects_invalid_image_indexes() -> None:
    client = _FakeChatClient()
    tool = VisionInspectionTool(
        client=cast(ChatCompletionClient, client),
        model_name="deepseek-v4-flash-vision-exp",
        user_request="inspect this",
        images=[_vision_image(3)],
        image_context_available=True,
    )

    result = asyncio.run(tool.run_autonomous_tool('{"image_indexes":[4]}'))

    assert "out of range" in result
    assert client.calls == []


def test_response_service_without_image_context_does_not_add_vision_tool() -> None:
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
