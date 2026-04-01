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
        allow_reasoning_fallback: bool = False,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class StoredResponseOutput:
    response_id: str
    content: str


@runtime_checkable
class ResponsesClient(Protocol):
    async def create_response(
        self,
        *,
        instructions: str,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = 1024,
        previous_response_id: str | None = None,
        allow_reasoning_fallback: bool = False,
    ) -> StoredResponseOutput: ...


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
        allow_reasoning_fallback: bool = False,
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
        allow_reasoning_fallback: bool = False,
    ) -> str:
        payload = {
            "model": model or self._default_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        data = await self._request("POST", "/chat/completions", json=payload)

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIClientError("No choices returned by model API")

        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()

        if allow_reasoning_fallback:
            reasoning_content = message.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content.strip():
                return reasoning_content.strip()

        raise AIClientError("Model returned empty response content")

    async def chat_completion_with_tools(
        self,
        *,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, object]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        allow_reasoning_fallback: bool = False,
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

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AIClientError("No choices returned by model API")

        message = choices[0].get("message", {})
        content = message.get("content")
        resolved_content: str | None = None
        if isinstance(content, str) and content.strip():
            resolved_content = content.strip()
        elif allow_reasoning_fallback:
            reasoning_content = message.get("reasoning_content")
            if isinstance(reasoning_content, str) and reasoning_content.strip():
                resolved_content = reasoning_content.strip()

        return ChatCompletionOutput(
            content=resolved_content,
            tool_calls=_parse_tool_calls(message),
        )

    async def create_response(
        self,
        *,
        instructions: str,
        messages: Sequence[ChatMessage],
        model: str | None = None,
        temperature: float = 0.7,
        max_output_tokens: int = 1024,
        previous_response_id: str | None = None,
        allow_reasoning_fallback: bool = False,
    ) -> StoredResponseOutput:
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "input": list(messages),
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
            "store": True,
        }
        if instructions.strip():
            payload["instructions"] = instructions
        if previous_response_id is not None:
            payload["previous_response_id"] = previous_response_id

        data = await self._request("POST", "/responses", json=payload)

        response_id = data.get("id")
        if not isinstance(response_id, str) or not response_id.strip():
            raise AIClientError("Responses API returned an invalid response id")

        content = _extract_response_output_text(
            data,
            allow_reasoning_fallback=allow_reasoning_fallback,
        )
        if content is None:
            raise AIClientError("Model returned empty response content")

        return StoredResponseOutput(response_id=response_id, content=content)

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


def _extract_response_output_text(
    data: dict[str, Any],
    *,
    allow_reasoning_fallback: bool,
) -> str | None:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    primary_sections: list[str] = []
    reasoning_sections: list[str] = []
    raw_output = data.get("output")
    if not isinstance(raw_output, list):
        return None

    for item in raw_output:
        if not isinstance(item, dict):
            continue
        _collect_response_sections(
            item,
            primary_sections=primary_sections,
            reasoning_sections=reasoning_sections,
        )

    if primary_sections:
        return "\n".join(primary_sections)
    if allow_reasoning_fallback and reasoning_sections:
        return "\n".join(reasoning_sections)
    return None


def _collect_response_sections(
    item: dict[str, Any],
    *,
    primary_sections: list[str],
    reasoning_sections: list[str],
) -> None:
    raw_content = item.get("content")
    if isinstance(raw_content, str) and raw_content.strip():
        primary_sections.append(raw_content.strip())
    elif isinstance(raw_content, list):
        for block in raw_content:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            text = _extract_response_block_text(block)
            if text is None:
                continue
            if block_type in {"output_text", "text"}:
                primary_sections.append(text)
            elif block_type in {"reasoning", "reasoning_text"}:
                reasoning_sections.append(text)

    item_type = item.get("type")
    if item_type in {"reasoning", "reasoning_text"}:
        text = _extract_response_block_text(item)
        if text is not None:
            reasoning_sections.append(text)


def _extract_response_block_text(block: dict[str, Any]) -> str | None:
    text = block.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()

    summary = block.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    if isinstance(summary, list):
        parts: list[str] = []
        for item in summary:
            if not isinstance(item, dict):
                continue
            summary_text = item.get("text")
            if isinstance(summary_text, str) and summary_text.strip():
                parts.append(summary_text.strip())
        if parts:
            return "\n".join(parts)

    return None
