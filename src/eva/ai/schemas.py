from __future__ import annotations

from typing import NotRequired, TypedDict, cast


class ToolFunctionCall(TypedDict):
    name: str
    arguments: str


class ToolCall(TypedDict):
    id: str
    type: str
    function: ToolFunctionCall


class TextPart(TypedDict):
    type: str
    text: str


class URLValue(TypedDict):
    url: str


class ImagePart(TypedDict):
    type: str
    image_url: URLValue


class VideoPart(TypedDict):
    type: str
    video_url: URLValue


class FileValue(TypedDict):
    file_data: str
    filename: str


class FilePart(TypedDict):
    type: str
    file: FileValue


ContentPart = TextPart | ImagePart | VideoPart | FilePart


class ChatMessage(TypedDict):
    role: str
    content: str | list[ContentPart]
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
