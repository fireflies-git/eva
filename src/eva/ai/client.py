from __future__ import annotations

import json as jsonlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import aiohttp

from eva.ai.schemas import ChatMessage
from eva.security.urls import PolicyResolver, URLPolicyError, validate_url_for_request


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
    reasoning_content: str | None = None


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
        thinking_enabled: bool | None = None,
        allow_private_outbound: bool = False,
        allowed_hosts: frozenset[str] | None = None,
        max_response_bytes: int = 1_048_576,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout_seconds = timeout_seconds
        self._thinking_enabled = thinking_enabled
        self._allow_private_outbound = allow_private_outbound
        self._allowed_hosts = allowed_hosts
        self._max_response_bytes = max(64 * 1024, max_response_bytes)
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                connector=aiohttp.TCPConnector(
                    resolver=PolicyResolver(allow_private=self._allow_private_outbound),
                    use_dns_cache=False,
                ),
            )

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
        payload = self._build_completion_payload(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
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
        payload = self._build_completion_payload(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
        )
        payload["tool_choice"] = "auto"
        data = await self._request("POST", "/chat/completions", json=payload)

        message = _extract_response_message(data)
        content = message.get("content")
        resolved_content: str | None = None
        if isinstance(content, str) and content.strip():
            resolved_content = content.strip()

        reasoning_content = message.get("reasoning_content")
        resolved_reasoning_content = (
            reasoning_content if isinstance(reasoning_content, str) else None
        )

        return ChatCompletionOutput(
            content=resolved_content,
            tool_calls=_parse_tool_calls(message),
            reasoning_content=resolved_reasoning_content,
        )

    def _build_completion_payload(
        self,
        *,
        messages: Sequence[ChatMessage],
        model: str | None,
        temperature: float,
        max_tokens: int,
        tools: Sequence[dict[str, object]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": list(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools is not None:
            payload["tools"] = list(tools)

        thinking_enabled = self._resolve_thinking_enabled(model)
        if thinking_enabled is not None:
            # DeepSeek V4 defaults to exposing a separate reasoning stream. Eva
            # only sends the visible content to Discord, so non-thinking mode is
            # the reliable default for normal user-facing replies.
            payload["thinking"] = {
                "type": "enabled" if thinking_enabled else "disabled",
            }
        return payload

    def _resolve_thinking_enabled(self, model: str | None) -> bool | None:
        if self._thinking_enabled is not None:
            return self._thinking_enabled

        resolved_model = (model or self._default_model).strip().lower()
        if resolved_model.startswith("deepseek-v4"):
            return False
        return None

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
            await validate_url_for_request(
                url,
                allow_private=self._allow_private_outbound,
                allowed_hosts=self._allowed_hosts,
            )
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json,
                allow_redirects=False,
            ) as response:
                text = await _read_response_text(response, max_bytes=self._max_response_bytes)
                if response.status != 200:
                    raise AIClientError(f"Model API error HTTP {response.status}")
                try:
                    data = jsonlib.loads(text)
                except Exception as exc:
                    raise AIClientError("Invalid JSON response") from exc
                if not isinstance(data, dict):
                    raise AIClientError("Invalid API response type")
                return data
        except TimeoutError as exc:
            raise AIClientError("Model API request timed out") from exc
        except aiohttp.ClientError as exc:
            raise AIClientError("Model API network error") from exc
        except URLPolicyError as exc:
            raise AIClientError(f"Model API URL blocked by outbound policy: {exc}") from exc


async def _read_response_text(response: aiohttp.ClientResponse, *, max_bytes: int) -> str:
    content = getattr(response, "content", None)
    if content is not None and hasattr(content, "iter_chunked"):
        chunks: list[bytes] = []
        total = 0
        async for chunk in content.iter_chunked(65_536):
            total += len(chunk)
            if total > max_bytes:
                raise AIClientError("Model API response exceeds configured size limit")
            chunks.append(chunk)
        raw = b"".join(chunks)
    elif content is not None and hasattr(content, "read"):
        raw = await content.read(max_bytes + 1)
    else:
        raise AIClientError("Model API response body cannot be read safely")
    if len(raw) > max_bytes:
        raise AIClientError("Model API response exceeds configured size limit")
    return raw.decode(getattr(response, "charset", None) or "utf-8", errors="replace")


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
