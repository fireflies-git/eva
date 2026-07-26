"""Web page fetch tool service using Playwright.

Fetches the visible text content of a URL via headless Chromium.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_AUTONOMOUS_TOOL_NAME = "fetch_web_page"


class PlaywrightService:
    """Fetches web page content using a headless Chromium browser.

    Implements the ``ToolService`` protocol for autonomous use.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        max_content_chars: int = 10000,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_content_chars = max_content_chars
        self._browser: Any = None
        self._playwright: Any = None

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
                    "Fetch and return the visible text content of a web page. "
                    "Useful for reading articles, documentation, or any public URL."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The full URL of the web page to fetch.",
                        }
                    },
                    "required": ["url"],
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

        url = parsed.get("url")
        if not isinstance(url, str) or not url.strip():
            return 'Error: Tool arguments must include a string "url".'

        if self._browser is None:
            return "Error: Browser is not started. Call start() first."

        try:
            content = await self._fetch_page(url.strip())
        except Exception as exc:
            logger.warning("Page fetch failed for %s: %s", url, exc)
            return f"Error: Failed to fetch page: {exc}"

        if len(content) > self._max_content_chars:
            content = content[: self._max_content_chars]
            content += "\n\n[content truncated]"

        return content

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch the headless Chromium browser.

        Imports Playwright lazily so the dependency is optional at
        import time.
        """
        if self._browser is not None:
            return

        try:
            from playwright.async_api import async_playwright

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
        except Exception:
            self._browser = None
            self._playwright = None
            logger.error("Failed to start Playwright browser", exc_info=True)
            raise

    async def close(self) -> None:
        """Shut down the browser and Playwright controller."""
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                logger.warning("Error closing Playwright browser", exc_info=True)
            self._browser = None

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                logger.warning("Error stopping Playwright controller", exc_info=True)
            self._playwright = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_page(self, url: str) -> str:
        """Navigate to *url* and return ``document.body.innerText``."""
        page = await self._browser.new_page()
        try:
            await page.goto(url, timeout=int(self._timeout_seconds * 1000))
            raw = await page.evaluate("document.body.innerText")
            return str(raw) if raw is not None else ""
        finally:
            await page.close()
