from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, NotRequired, TypedDict, cast


class ToolFunctionCall(TypedDict):
    name: str
    arguments: str


class ToolCall(TypedDict):
    id: str
    type: str
    function: ToolFunctionCall


class TextPart(TypedDict):
    type: Literal["text"]
    text: str


class URLValue(TypedDict):
    url: str


class ImagePart(TypedDict):
    type: Literal["image_url"]
    image_url: URLValue


class VideoPart(TypedDict):
    type: Literal["video_url"]
    video_url: URLValue


class FileValue(TypedDict):
    file_data: str
    filename: str


class FilePart(TypedDict):
    type: Literal["file"]
    file: FileValue


ContentPart = TextPart | ImagePart | VideoPart | FilePart
TextContentPart = TextPart
ImageURLContentPart = ImagePart
ImageURL = URLValue
MessageContent = str | list[ContentPart]


@dataclass(frozen=True, slots=True)
class VisionImage:
    message_id: int
    filename: str
    mime_type: str
    data: bytes = field(repr=False)


class ChatMessage(TypedDict):
    role: str
    content: MessageContent
    reasoning_content: NotRequired[str | None]
    tool_call_id: NotRequired[str]
    name: NotRequired[str]
    tool_calls: NotRequired[list[ToolCall]]


def visible_text(message: ChatMessage) -> str:
    """Return only human-readable text, never data URLs or file bytes."""
    content = message["content"]
    if isinstance(content, str):
        return content
    texts: list[str] = []
    for part in content:
        if part["type"] == "text":
            texts.append(cast(TextPart, part)["text"])
    return "\n".join(texts)
