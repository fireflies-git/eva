from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

from eva.ai.client import ChatCompletionOutput, ModelToolCall
from eva.ai.respond import ResponseService
from eva.terminal import TerminalService
from eva.tools import ToolService


class FakeToolClient:
    def __init__(self) -> None:
        self.tool_calls: list[dict[str, object]] = []
        self.chat_calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.chat_calls.append(kwargs)
        return "plain fallback"

    async def chat_completion_with_tools(self, **kwargs: object) -> ChatCompletionOutput:
        self.tool_calls.append(kwargs)
        messages = cast(list[dict[str, Any]], kwargs["messages"])
        if not any(message.get("role") == "tool" for message in messages):
            return ChatCompletionOutput(
                content=None,
                tool_calls=[
                    ModelToolCall(
                        id="tool-1",
                        name="run_terminal_command",
                        arguments=json.dumps({"command": "pwd"}),
                    )
                ],
            )
        return ChatCompletionOutput(content="used tool output", tool_calls=[])


def test_response_service_uses_terminal_tool_loop(tmp_path: Path) -> None:
    client = FakeToolClient()
    terminal_service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )
    service = ResponseService(
        client=client,
        model_name="model",
        tool_services=[terminal_service],
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[],
            history_messages=[],
            user_message="where am i running",
            reply_context=None,
            requester_context=None,
        )
    )

    assert reply.content == "used tool output"
    assert len(client.tool_calls) == 2
    assert client.chat_calls == []


class FakeChatClient:
    def __init__(self) -> None:
        self.chat_calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.chat_calls.append(kwargs)
        return "chat reply"


class FakeToolService:
    @property
    def autonomous_tool_name(self) -> str:
        return "fake_tool"

    def build_autonomous_tool_definition(self) -> dict[str, object]:
        return {"type": "function", "function": {"name": "fake_tool"}}

    async def run_autonomous_tool(self, arguments: str) -> str:
        return "tool result"


class OverCallingToolClient:
    """First round emits more tool calls than the per-round cap allows."""

    def __init__(self, call_count: int) -> None:
        self.call_count = call_count
        self.tool_calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        return "plain fallback"

    async def chat_completion_with_tools(self, **kwargs: object) -> ChatCompletionOutput:
        self.tool_calls.append(kwargs)
        messages = cast(list[dict[str, Any]], kwargs["messages"])
        if not any(message.get("role") == "tool" for message in messages):
            return ChatCompletionOutput(
                content=None,
                tool_calls=[
                    ModelToolCall(
                        id=f"tool-{index}",
                        name="fake_tool",
                        arguments="{}",
                    )
                    for index in range(self.call_count)
                ],
            )
        return ChatCompletionOutput(content="done", tool_calls=[])


def test_tool_loop_caps_unanswered_tool_calls_on_assistant_message() -> None:
    client = OverCallingToolClient(call_count=7)
    tool_services: list[ToolService] = [FakeToolService()]
    service = ResponseService(
        client=client,
        model_name="model",
        tool_services=tool_services,
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[],
            history_messages=[],
            user_message="use the tool a lot",
            reply_context=None,
            requester_context=None,
        )
    )

    assert reply.content == "done"
    assert len(client.tool_calls) == 2

    second_round_messages = cast(list[dict[str, Any]], client.tool_calls[1]["messages"])
    assistant_messages = [
        message for message in second_round_messages if message.get("role") == "assistant"
    ]
    tool_messages = [
        message for message in second_round_messages if message.get("role") == "tool"
    ]
    # Every tool_call on the assistant message must have a matching tool
    # response, or the API rejects the next round with HTTP 400.
    assert len(assistant_messages) == 1
    assert len(assistant_messages[0]["tool_calls"]) == 5
    assert len(tool_messages) == 5
    answered_ids = {tool_call["id"] for tool_call in assistant_messages[0]["tool_calls"]}
    assert {message["tool_call_id"] for message in tool_messages} == answered_ids


def test_response_service_uses_chat_completion_with_local_history() -> None:
    client = FakeChatClient()
    service = ResponseService(client=client, model_name="model")

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[{"role": "user", "content": "ambient context"}],
            history_messages=[{"role": "assistant", "content": "old reply"}],
            user_message="new question",
            reply_context=None,
            requester_context=None,
        )
    )

    assert reply.content == "chat reply"
    assert len(client.chat_calls) == 1
    payload = client.chat_calls[0]
    assert payload["model"] == "model"
    messages = cast(list[dict[str, str]], payload["messages"])
    assert messages == [
        {"role": "system", "content": "prompt"},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "ambient context"},
        {"role": "user", "content": "new question"},
    ]
