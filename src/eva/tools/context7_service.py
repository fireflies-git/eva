"""Documentation lookup tool service using the Context7 API.

Searches library/framework documentation via the Context7 search API and
returns a numbered list of results.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from eva.security.urls import PolicyResolver, URLPolicyError, validate_url_for_request

logger = logging.getLogger(__name__)

_AUTONOMOUS_TOOL_NAME = "lookup_documentation"
_API_BASE_URL = "https://api.context7.com/v1/search"
_MAX_RESPONSE_BYTES = 1_048_576
_RESPONSE_CHUNK_BYTES = 65_536


class Context7Service:
    """Searches documentation for a library via the Context7 API.

    Implements the ``ToolService`` protocol for autonomous use.
    """

    def __init__(
        self,
        *,
        api_key: str,
        timeout_seconds: float = 15.0,
        max_results: int = 3,
        allow_private_outbound: bool = False,
        allowed_hosts: frozenset[str] | None = None,
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_results = max_results
        self._allow_private_outbound = allow_private_outbound
        self._allowed_hosts = allowed_hosts
        self._session: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # ToolService protocol
    # ------------------------------------------------------------------

    @property
    def autonomous_tool_name(self) -> str:
        return _AUTONOMOUS_TOOL_NAME

    def build_autonomous_tool_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": _AUTONOMOUS_TOOL_NAME,
                "description": (
                    "Search the official documentation of a specific library "
                    "or framework and return relevant results with titles, "
                    "URLs, and snippets."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query or question about the library.",
                        },
                        "library": {
                            "type": "string",
                            "description": (
                                "The name of the library or framework to search within "
                                "(e.g. 'discord.py', 'pydantic', 'fastapi')."
                            ),
                        },
                    },
                    "required": ["query", "library"],
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

        library = parsed.get("library")
        if not isinstance(library, str) or not library.strip():
            return 'Error: Tool arguments must include a string "library".'

        if self._session is None:
            return "Error: Context7 service is not started. Call start() first."

        try:
            data = await self._api_request(query.strip(), library.strip())
        except Exception as exc:
            logger.warning(
                "Context7 API request failed error_type=%s",
                type(exc).__name__,
            )
            return "Error: Documentation lookup failed."

        formatted = self._format_results(data)
        if not formatted:
            return "No documentation results found."

        return "[UNTRUSTED_DOCUMENTATION_DATA]\n" + formatted

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open the ``aiohttp.ClientSession``."""
        if self._session is not None:
            return
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        self._session = aiohttp.ClientSession(
            timeout=timeout,
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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _api_request(self, query: str, library: str) -> dict[str, Any]:
        """POST the search request to the Context7 API."""
        if self._session is None:
            raise RuntimeError("Context7 service is not started")

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            await validate_url_for_request(
                _API_BASE_URL,
                allow_private=self._allow_private_outbound,
                allowed_hosts=self._allowed_hosts,
            )
            async with self._session.post(
                _API_BASE_URL,
                headers=headers,
                json={"query": query, "library": library},
                allow_redirects=False,
            ) as response:
                body = await _read_response_body(response, max_bytes=_MAX_RESPONSE_BYTES)
                text = body.decode(getattr(response, "charset", None) or "utf-8", errors="replace")
                if response.status != 200:
                    raise RuntimeError(f"Context7 API error HTTP {response.status}")
                try:
                    data = json.loads(text)
                except Exception as exc:
                    raise RuntimeError("Invalid Context7 JSON response") from exc
                if not isinstance(data, dict):
                    raise RuntimeError("Invalid Context7 API response type")
                return data
        except TimeoutError as exc:
            raise RuntimeError("Context7 API request timed out") from exc
        except aiohttp.ClientError as exc:
            raise RuntimeError("Context7 API network error") from exc
        except URLPolicyError as exc:
            raise RuntimeError(f"Context7 API URL blocked by outbound policy: {exc}") from exc

    def _format_results(self, data: dict[str, Any]) -> str:
        """Turn the API response dict into a numbered list of results."""
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

            title = self._string_or_none(item.get("title"))
            url = self._string_or_none(item.get("url"))
            if not title or not url:
                continue

            snippet = self._string_or_none(item.get("snippet"))

            count += 1
            lines.append(f"{count}. {title}")
            lines.append(f"   URL: {url}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def _string_or_none(value: Any) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None


async def _read_response_body(response: Any, *, max_bytes: int) -> bytes:
    """Read an aiohttp response with a hard cap before decoding or parsing."""
    content = getattr(response, "content", None)
    if content is not None and hasattr(content, "iter_chunked"):
        chunks: list[bytes] = []
        total = 0
        async for chunk in content.iter_chunked(_RESPONSE_CHUNK_BYTES):
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError("Context7 response exceeded the configured size limit")
            chunks.append(chunk)
        return b"".join(chunks)
    if content is not None and hasattr(content, "read"):
        raw = await content.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise RuntimeError("Context7 response exceeded the configured size limit")
        return raw
    raise RuntimeError("Context7 response body cannot be read safely")
