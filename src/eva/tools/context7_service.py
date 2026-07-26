"""Documentation lookup tool service using the Context7 API.

Searches library/framework documentation via the Context7 search API and
returns a numbered list of results.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

_AUTONOMOUS_TOOL_NAME = "lookup_documentation"
_API_BASE_URL = "https://api.context7.com/v1/search"


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
    ) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_results = max_results
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
            logger.warning("Context7 API request failed: %s", exc)
            return f"Error: Documentation lookup failed: {exc}"

        formatted = self._format_results(data)
        if not formatted:
            return "No documentation results found."

        return formatted

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open the ``aiohttp.ClientSession``."""
        if self._session is not None:
            return
        timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
        self._session = aiohttp.ClientSession(timeout=timeout)

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
            async with self._session.post(
                _API_BASE_URL,
                headers=headers,
                json={"query": query, "library": library},
            ) as response:
                text = await response.text()
                if response.status != 200:
                    raise RuntimeError(
                        f"Context7 API error HTTP {response.status}: {text[:300]}"
                    )
                try:
                    data = await response.json()
                except Exception as exc:
                    raise RuntimeError(
                        f"Invalid Context7 JSON response: {text[:300]}"
                    ) from exc
                if not isinstance(data, dict):
                    raise RuntimeError("Invalid Context7 API response type")
                return data
        except TimeoutError as exc:
            raise RuntimeError("Context7 API request timed out") from exc
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"Context7 API network error: {exc}") from exc

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
