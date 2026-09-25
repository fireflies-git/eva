from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, cast

from eva.ai.client import AIClientError, ChatCompletionOutput, ModelToolCall
from eva.ai.respond import ResponseService
from eva.terminal import TerminalService
from eva.tools import ToolAuthorizer, ToolExecutionContext, ToolService


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
                reasoning_content="private reasoning",
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
        tool_authorizer=ToolAuthorizer(),
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[],
            history_messages=[],
            user_message="where am i running",
            reply_context=None,
            requester_context=None,
            tool_context=ToolExecutionContext(requester_id=1, is_owner=True),
        )
    )

    assert reply.content == "used tool output"
    assert len(client.tool_calls) == 2
    assert client.chat_calls == []

    second_round_messages = cast(list[dict[str, Any]], client.tool_calls[1]["messages"])
    assistant_message = next(
        message for message in second_round_messages if message.get("role") == "assistant"
    )
    assert assistant_message["reasoning_content"] == "private reasoning"


class FakeChatClient:
    def __init__(self) -> None:
        self.chat_calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.chat_calls.append(kwargs)
        return "chat reply"


class RecoveringChatClient:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = responses
        self.chat_calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.chat_calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeToolService:
    @property
    def autonomous_tool_name(self) -> str:
        return "fake_tool"

    def build_autonomous_tool_definition(self) -> dict[str, object]:
        return {"type": "function", "function": {"name": "fake_tool"}}

    async def run_autonomous_tool(self, arguments: str) -> str:
        return "tool result"


class ProtectedToolService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    @property
    def autonomous_tool_name(self) -> str:
        return self.name

    def build_autonomous_tool_definition(self) -> dict[str, object]:
        return {"type": "function", "function": {"name": self.name}}

    async def run_autonomous_tool(self, arguments: str) -> str:
        self.calls += 1
        return "tool result"


class AuthorizeThenDenyToolAuthorizer(ToolAuthorizer):
    def __init__(self) -> None:
        super().__init__()
        self.checks = 0

    def is_allowed(
        self,
        tool_name: str,
        context: ToolExecutionContext | None,
    ) -> bool:
        self.checks += 1
        return self.checks == 1


def test_unprivileged_requester_never_receives_autonomous_tool_definitions() -> None:
    client = FakeToolClient()
    tool_services: list[ToolService] = [
        ProtectedToolService("run_terminal_command"),
        ProtectedToolService("fetch_web_page"),
        ProtectedToolService("lookup_documentation"),
    ]
    service = ResponseService(
        client=client,
        model_name="model",
        tool_services=tool_services,
        tool_authorizer=ToolAuthorizer(),
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[],
            history_messages=[],
            user_message="try the tools",
            reply_context=None,
            requester_context=None,
            tool_context=ToolExecutionContext(
                requester_id=42,
                is_whitelisted=True,
                account_mode="standalone",
            ),
        )
    )

    assert reply.content == "plain fallback"
    assert client.tool_calls == []
    assert len(client.chat_calls) == 1
    assert all(cast(ProtectedToolService, tool).calls == 0 for tool in tool_services)


def test_tool_authorization_is_rechecked_before_execution() -> None:
    client = FakeToolClient()
    terminal = ProtectedToolService("run_terminal_command")
    service = ResponseService(
        client=client,
        model_name="model",
        tool_services=[terminal],
        tool_authorizer=AuthorizeThenDenyToolAuthorizer(),
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[],
            history_messages=[],
            user_message="use the tool",
            reply_context=None,
            requester_context=None,
            tool_context=ToolExecutionContext(requester_id=1, is_owner=True),
        )
    )

    assert reply.content == "used tool output"
    assert terminal.calls == 0
    second_round_messages = cast(list[dict[str, Any]], client.tool_calls[1]["messages"])
    tool_message = next(
        message for message in second_round_messages if message.get("role") == "tool"
    )
    assert "not authorized" in tool_message["content"]


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
        tool_authorizer=ToolAuthorizer(protected_tool_names={"fake_tool"}),
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[],
            history_messages=[],
            user_message="use the tool a lot",
            reply_context=None,
            requester_context=None,
            tool_context=ToolExecutionContext(requester_id=1, is_admin=True),
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


def test_response_service_prefers_canonical_discord_context() -> None:
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
        {"role": "user", "content": "ambient context"},
        {"role": "user", "content": "new question"},
    ]


def test_response_service_uses_local_history_when_discord_context_is_empty() -> None:
    client = FakeChatClient()
    service = ResponseService(client=client, model_name="model")

    asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[],
            history_messages=[{"role": "assistant", "content": "old reply"}],
            user_message="new question",
            reply_context=None,
            requester_context=None,
        )
    )

    messages = cast(list[dict[str, str]], client.chat_calls[0]["messages"])
    assert messages == [
        {"role": "system", "content": "prompt"},
        {
            "role": "assistant",
            "content": "[UNTRUSTED_HISTORY_DATA]\nold reply",
        },
        {"role": "user", "content": "new question"},
    ]


def test_response_service_recovers_when_model_returns_hidden_reasoning_only() -> None:
    client = RecoveringChatClient(
        [
            "<think>the model should refuse this request</think>",
            "i can't help with that, but i can help with something safe",
        ]
    )
    service = ResponseService(client=client, model_name="model")

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[],
            history_messages=[],
            user_message="do the unsafe thing",
            reply_context=None,
            requester_context=None,
        )
    )

    assert reply.content == "i can't help with that, but i can help with something safe"
    assert len(client.chat_calls) == 2
    recovery_messages = cast(list[dict[str, str]], client.chat_calls[1]["messages"])
    assert "did not contain a visible user-facing answer" in recovery_messages[0]["content"]


def test_response_service_uses_visible_fallback_when_recovery_fails() -> None:
    client = RecoveringChatClient(
        [
            "<think>private reasoning only</think>",
            AIClientError("provider unavailable"),
        ]
    )
    service = ResponseService(client=client, model_name="model")

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="prompt",
            context_messages=[],
            history_messages=[],
            user_message="try again",
            reply_context=None,
            requester_context=None,
        )
    )

    assert reply.content == "i couldn't get a visible answer out of that. please try again."
    assert len(client.chat_calls) == 2
