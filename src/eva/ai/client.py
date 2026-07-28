from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import aiohttp

from eva.ai.schemas import ChatMessage


class AIClientError(RuntimeError):
    pass


class ChatCompletionClient(Protocol):
    async def chat_completion(
        self,
        *,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ModelToolCall:
    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ChatCompletionOutput:
    content: str | None
    tool_calls: list[ModelToolCall]


@runtime_checkable
class ToolChatCompletionClient(Protocol):
    async def chat_completion_with_tools(
        self,
        *,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, object]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ChatCompletionOutput: ...


class OpenAICompatibleClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_model: str,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout_seconds = timeout_seconds
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def list_models(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/models")
        models = data.get("data")
        if not isinstance(models, list):
            raise AIClientError("Invalid /models response shape")
        return models

    async def chat_completion(
        self,
        *,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        payload = {
            "model": model or self._default_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = await self._request("POST", "/chat/completions", json=payload)

        message = _extract_response_message(data)
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

        raise AIClientError("Model returned empty response content")

    async def chat_completion_with_tools(
        self,
        *,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, object]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> ChatCompletionOutput:
        payload = {
            "model": model or self._default_model,
            "messages": list(messages),
            "tools": list(tools),
            "tool_choice": "auto",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = await self._request("POST", "/chat/completions", json=payload)

        message = _extract_response_message(data)
        content = message.get("content")
        resolved_content: str | None = None
        if isinstance(content, str) and content.strip():
            resolved_content = content.strip()

        return ChatCompletionOutput(
            content=resolved_content,
            tool_calls=_parse_tool_calls(message),
        )

    async def _request(
        self,
        method: str,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._session is None:
            raise AIClientError("AI client is not started")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}{path}"

        try:
            async with self._session.request(method, url, headers=headers, json=json) as response:
                text = await response.text()
                if response.status != 200:
                    snippet = text[:300]
                    raise AIClientError(f"Model API error HTTP {response.status}: {snippet}")
                try:
                    data = await response.json()
                except Exception as exc:
                    raise AIClientError(f"Invalid JSON response: {text[:300]}") from exc
                if not isinstance(data, dict):
                    raise AIClientError("Invalid API response type")
                return data
        except TimeoutError as exc:
            raise AIClientError("Model API request timed out") from exc
        except aiohttp.ClientError as exc:
            raise AIClientError(f"Model API network error: {exc}") from exc


def _extract_response_message(data: dict[str, Any]) -> dict[str, Any]:
    """Return the first choice's message object, validating the response shape."""
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise AIClientError("No choices returned by model API")
    first = choices[0]
    if not isinstance(first, dict):
        raise AIClientError("Invalid choice shape in model API response")
    message = first.get("message")
    if not isinstance(message, dict):
        raise AIClientError("Invalid message shape in model API response")
    return message


def _parse_tool_calls(message: dict[str, Any]) -> list[ModelToolCall]:
    raw_tool_calls = message.get("tool_calls")
    if not isinstance(raw_tool_calls, list):
        return []

    parsed: list[ModelToolCall] = []
    for raw_tool_call in raw_tool_calls:
        if not isinstance(raw_tool_call, dict):
            continue

        tool_id = raw_tool_call.get("id")
        if not isinstance(tool_id, str) or not tool_id.strip():
            continue

        function = raw_tool_call.get("function")
        if not isinstance(function, dict):
            continue

        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(arguments, str):
            continue

        parsed.append(ModelToolCall(id=tool_id, name=name, arguments=arguments))

    return parsed
