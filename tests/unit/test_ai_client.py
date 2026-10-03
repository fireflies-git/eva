import asyncio
from typing import Any

import pytest

from eva.ai.client import AIClientError, OpenAICompatibleClient


class StubAIClient(OpenAICompatibleClient):
    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(
            api_key="test",
            base_url="https://example.com/v1",
            default_model="model",
            timeout_seconds=30.0,
        )
        self._payload = payload
        self.requests: list[dict[str, Any]] = []

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if json is not None:
            self.requests.append(json)
        return self._payload


def _chat(client: OpenAICompatibleClient) -> str:
    return asyncio.run(
        client.chat_completion(messages=[{"role": "user", "content": "hi"}])
    )


def test_chat_completion_returns_stripped_content() -> None:
    client = StubAIClient({"choices": [{"message": {"content": "  hello  "}}]})

    assert _chat(client) == "hello"


def test_chat_completion_rejects_missing_choices() -> None:
    client = StubAIClient({})

    with pytest.raises(AIClientError, match="No choices"):
        _chat(client)


def test_chat_completion_rejects_non_dict_choice() -> None:
    for bad_first in (None, "garbage", 42):
        client = StubAIClient({"choices": [bad_first]})

        with pytest.raises(AIClientError, match="Invalid choice shape"):
            _chat(client)


def test_chat_completion_rejects_non_dict_message() -> None:
    for bad_message in (None, "garbage", 42):
        client = StubAIClient({"choices": [{"message": bad_message}]})

        with pytest.raises(AIClientError, match="Invalid message shape"):
            _chat(client)


def test_chat_completion_rejects_empty_content() -> None:
    client = StubAIClient({"choices": [{"message": {"content": "   "}}]})

    with pytest.raises(AIClientError, match="empty response content"):
        _chat(client)


def test_chat_completion_with_tools_rejects_malformed_message() -> None:
    client = StubAIClient({"choices": [{"message": None}]})

    with pytest.raises(AIClientError, match="Invalid message shape"):
        asyncio.run(client.chat_completion_with_tools(messages=[], tools=[]))


def test_chat_completion_with_tools_parses_tool_calls() -> None:
    client = StubAIClient(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "shell", "arguments": '{"cmd":"ls"}'},
                            }
                        ],
                    }
                }
            ]
        }
    )

    output = asyncio.run(client.chat_completion_with_tools(messages=[], tools=[]))

    assert output.content is None
    assert len(output.tool_calls) == 1
    assert output.tool_calls[0].id == "call-1"
    assert output.tool_calls[0].name == "shell"


def test_chat_completion_with_tools_preserves_reasoning_content() -> None:
    client = StubAIClient(
        {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning_content": "private reasoning",
                        "tool_calls": [],
                    }
                }
            ]
        }
    )

    output = asyncio.run(client.chat_completion_with_tools(messages=[], tools=[]))

    assert output.reasoning_content == "private reasoning"


def test_deepseek_v4_requests_disable_thinking_by_default() -> None:
    client = OpenAICompatibleClient(
        api_key="test",
        base_url="https://api.deepseek.com",
        default_model="deepseek-v4-flash",
        timeout_seconds=30.0,
    )

    async def request(
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert json is not None
        assert json["thinking"] == {"type": "disabled"}
        return {"choices": [{"message": {"content": "reply"}}]}

    client._request = request  # type: ignore[method-assign]

    assert _chat(client) == "reply"


def test_glm_requests_include_reasoning_policy_and_top_p() -> None:
    client = OpenAICompatibleClient(
        api_key="test",
        base_url="https://api.z.ai/api/paas/v4",
        default_model="glm-5.3-flash",
        timeout_seconds=30.0,
        reasoning_effort="low",
        clear_thinking=True,
    )
    captured: dict[str, Any] = {}

    async def request(
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert json is not None
        captured.update(json)
        return {"choices": [{"finish_reason": "stop", "message": {"content": "reply"}}]}

    client._request = request  # type: ignore[method-assign]
    assert _chat(client) == "reply"
    assert captured["top_p"] == 0.95
    assert captured["reasoning_effort"] == "low"
    assert captured["thinking"] == {"type": "enabled", "clear_thinking": True}


def test_glm_tool_continuation_can_preserve_thinking_history() -> None:
    client = OpenAICompatibleClient(
        api_key="test",
        base_url="https://api.z.ai/api/paas/v4",
        default_model="glm-5.3-flash",
        timeout_seconds=30.0,
    )
    payload = client._build_completion_payload(
        messages=[],
        model="glm-5.3-flash",
        temperature=0.7,
        max_tokens=32,
        tools=[],
        clear_thinking=False,
    )
    assert payload["thinking"] == {"type": "enabled", "clear_thinking": False}


def test_glm_tool_arguments_accept_objects_and_finish_reason() -> None:
    client = StubAIClient(
        {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {"name": "probe", "arguments": {"ok": True}},
                            }
                        ],
                    },
                }
            ]
        }
    )
    output = asyncio.run(client.chat_completion_with_tools(messages=[], tools=[]))
    assert output.finish_reason == "tool_calls"
    assert output.tool_calls[0].arguments == '{"ok":true}'


def test_completion_rejects_non_success_finish_reason() -> None:
    client = StubAIClient(
        {"choices": [{"finish_reason": "length", "message": {"content": "partial"}}]}
    )
    with pytest.raises(AIClientError, match="finish_reason=length"):
        _chat(client)
