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

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
