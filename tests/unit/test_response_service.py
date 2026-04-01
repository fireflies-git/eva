from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

from eva.ai.client import AIClientError, ChatCompletionOutput, ModelToolCall, StoredResponseOutput
from eva.ai.respond import ResponseService
from eva.terminal import TerminalService


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
        terminal_service=terminal_service,
        autonomous_terminal_access=True,
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
    assert reply.response_id is None
    assert len(client.tool_calls) == 2
    assert client.chat_calls == []


class FakeResponsesClient:
    def __init__(self) -> None:
        self.response_calls: list[dict[str, object]] = []
        self.chat_calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.chat_calls.append(kwargs)
        return "plain fallback"

    async def create_response(self, **kwargs: object) -> StoredResponseOutput:
        self.response_calls.append(kwargs)
        previous_response_id = cast(str | None, kwargs.get("previous_response_id"))
        if previous_response_id == "bad-prev" and len(self.response_calls) == 1:
            raise AIClientError("previous_response_id is invalid")
        return StoredResponseOutput(response_id="resp-2", content="stored reply")


def test_response_service_uses_responses_api_and_reseeds_on_invalid_previous_id() -> None:
    client = FakeResponsesClient()
    service = ResponseService(client=client, model_name="model")

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[{"role": "user", "content": "ambient context"}],
            history_messages=[{"role": "assistant", "content": "old reply"}],
            user_message="new question",
            reply_context=None,
            requester_context=None,
            previous_response_id="bad-prev",
        )
    )

    assert reply.content == "stored reply"
    assert reply.response_id == "resp-2"
    assert client.chat_calls == []
    assert len(client.response_calls) == 2
    first_messages = cast(list[dict[str, str]], client.response_calls[0]["messages"])
    second_messages = cast(list[dict[str, str]], client.response_calls[1]["messages"])
    assert client.response_calls[0]["previous_response_id"] == "bad-prev"
    assert len(first_messages) == 2
    assert len(second_messages) == 3
    assert second_messages[0]["content"] == "old reply"
