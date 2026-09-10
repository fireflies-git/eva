from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict


class TextContentPart(TypedDict):
    type: Literal["text"]
    text: str


class ImageURL(TypedDict):
    url: str


class ImageURLContentPart(TypedDict):
    type: Literal["image_url"]
    image_url: ImageURL


ContentPart = TextContentPart | ImageURLContentPart
MessageContent = str | list[ContentPart]


@dataclass(frozen=True, slots=True)
class VisionImage:
    message_id: int
    filename: str
    mime_type: str
    data: bytes = field(repr=False)


class ToolFunctionCall(TypedDict):
    name: str
    arguments: str


class ToolCall(TypedDict):
    id: str
    type: str
    function: ToolFunctionCall


class ChatMessage(TypedDict):
    role: str
    content: MessageContent
    reasoning_content: NotRequired[str | None]
    tool_call_id: NotRequired[str]
    name: NotRequired[str]
    tool_calls: NotRequired[list[ToolCall]]
