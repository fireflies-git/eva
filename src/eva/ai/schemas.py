from __future__ import annotations

from typing import NotRequired, TypedDict


class ToolFunctionCall(TypedDict):
    name: str
    arguments: str


class ToolCall(TypedDict):
    id: str
    type: str
    function: ToolFunctionCall


class ChatMessage(TypedDict):
    role: str
    content: str
    tool_call_id: NotRequired[str]
    name: NotRequired[str]
    tool_calls: NotRequired[list[ToolCall]]
