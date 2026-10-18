"""Live web search tool service using the Exa API.

Sends the recommended Exa ``/search`` request (auto type, token-efficient
highlights) and returns a numbered list of results for the model.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from eva.security.urls import PolicyResolver, URLPolicyError, validate_url_for_request

logger = logging.getLogger(__name__)

_AUTONOMOUS_TOOL_NAME = "web_search"
_API_URL = "https://api.exa.ai/search"
_MAX_RESPONSE_BYTES = 1_048_576
_RESPONSE_CHUNK_BYTES = 65_536
_MAX_HIGHLIGHT_CHARS = 600
_MAX_OBJECTIVE_CHARS = 4096


class ExaService:
    """Searches the live web via the Exa API.

    Implements the ``ToolService`` protocol for autonomous use.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 20.0,
        max_results: int = 5,
        allow_private_outbound: bool = False,
        allowed_hosts: frozenset[str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_results = max_results
        self._allow_private_outbound = allow_private_outbound
        self._allowed_hosts = allowed_hosts
        self._session: aiohttp.ClientSession | None = None

    @property
    def autonomous_tool_name(self) -> str:
        return _AUTONOMOUS_TOOL_NAME

    def build_autonomous_tool_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": _AUTONOMOUS_TOOL_NAME,
                "description": (
                    "Search the live web and return the most relevant URLs with "
                    "excerpts. Use for fresh information beyond your training data."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": (
                                "Natural-language search query, including any time frame "
                                "or source preference (e.g. 'latest Python 3.14 release notes')."
                            ),
                        },
                        "objective": {
                            "type": "string",
                            "description": (
                                "Goal for this search: which documents should rank first "
                                "and what facts to pull from them."
                            ),
                        },
                    },
                    "required": ["query", "objective"],
                    "additionalProperties": False,
                },
            },
        }

    async def run_autonomous_tool(self, arguments: str) -> str:
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return "Error: Tool arguments must be valid JSON."

        if not isinstance(parsed, dict):
            return "Error: Tool arguments must be a JSON object."

        query = parsed.get("query")
        if not isinstance(query, str) or not query.strip():
            return 'Error: Tool arguments must include a string "query".'

        objective = parsed.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            objective = None

        if self._session is None:
            return "Error: Exa service is not started. Call start() first."

        try:
            data = await self._api_request(query.strip(), objective)
        except Exception as exc:
            logger.warning("Exa API request failed error_type=%s", type(exc).__name__)
            return "Error: Web search failed."

        formatted = self._format_results(data)
        if not formatted:
            return "No web search results found."

        return "[UNTRUSTED_WEB_DATA]\n" + formatted

    async def start(self) -> None:
        """Open the ``aiohttp.ClientSession``."""
        if self._session is not None:
            return
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self._timeout_seconds),
            connector=aiohttp.TCPConnector(
                resolver=PolicyResolver(allow_private=self._allow_private_outbound),
                use_dns_cache=False,
            ),
        )

    async def close(self) -> None:
        """Close the ``aiohttp.ClientSession``."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    def _build_payload(self, query: str, objective: str | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": query,
            "type": "auto",
            "contents": {"highlights": True},
        }
        if objective is not None:
            payload["objective"] = objective[:_MAX_OBJECTIVE_CHARS]
        return payload

    async def _api_request(self, query: str, objective: str | None) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("Exa service is not started")

        headers = {"x-api-key": self._api_key, "Content-Type": "application/json"}

        try:
            await validate_url_for_request(
                _API_URL,
                allow_private=self._allow_private_outbound,
                allowed_hosts=self._allowed_hosts,
            )
            async with self._session.post(
                _API_URL,
                headers=headers,
                json=self._build_payload(query, objective),
                allow_redirects=False,
            ) as response:
                body = await _read_response_body(response, max_bytes=_MAX_RESPONSE_BYTES)
                if response.status != 200:
                    raise RuntimeError(f"Exa API error HTTP {response.status}")
                text = body.decode(getattr(response, "charset", None) or "utf-8", errors="replace")
                try:
                    data = json.loads(text)
                except Exception as exc:
                    raise RuntimeError("Invalid Exa JSON response") from exc
                if not isinstance(data, dict):
                    raise RuntimeError("Invalid Exa API response type")
                return data
        except TimeoutError as exc:
            raise RuntimeError("Exa API request timed out") from exc
        except aiohttp.ClientError as exc:
            raise RuntimeError("Exa API network error") from exc
        except URLPolicyError as exc:
            raise RuntimeError(f"Exa API URL blocked by outbound policy: {exc}") from exc

    def _format_results(self, data: dict[str, Any]) -> str:
        raw_results = data.get("results")
        if not isinstance(raw_results, list):
            return ""

        lines: list[str] = []
        count = 0
        for item in raw_results:
            if count >= self._max_results:
                break
            if not isinstance(item, dict):
                continue

            url = _string_or_none(item.get("url"))
            if not url:
                continue

            count += 1
            lines.append(f"{count}. {_string_or_none(item.get('title')) or url}")
            lines.append(f"   URL: {url}")
            published = _string_or_none(item.get("publishedDate"))
            if published:
                lines.append(f"   Published: {published}")
            for highlight in _highlights(item):
                lines.append(f"   {highlight}")
            lines.append("")

        return "\n".join(lines).strip()


def _highlights(item: dict[str, Any]) -> list[str]:
    raw = item.get("highlights")
    if not isinstance(raw, list):
        return []
    cleaned = [_string_or_none(entry) for entry in raw]
    return [" ".join(text.split())[:_MAX_HIGHLIGHT_CHARS] for text in cleaned if text]


def _string_or_none(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


async def _read_response_body(response: Any, *, max_bytes: int) -> bytes:
    """Read an aiohttp response with a hard cap before decoding or parsing."""
    content = getattr(response, "content", None)
    if content is None or not hasattr(content, "iter_chunked"):
        raise RuntimeError("Exa response body cannot be read safely")
    chunks: list[bytes] = []
    total = 0
    async for chunk in content.iter_chunked(_RESPONSE_CHUNK_BYTES):
        total += len(chunk)
        if total > max_bytes:
            raise RuntimeError("Exa response exceeded the configured size limit")
        chunks.append(chunk)
    return b"".join(chunks)
