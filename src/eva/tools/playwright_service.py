"""Web page fetch tool service using Playwright.

Fetches the visible text content of a URL via headless Chromium.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from eva.security.urls import URLPolicyError, validate_url_for_request

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
        allow_private_outbound: bool = False,
        allowed_hosts: frozenset[str] | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._max_content_chars = max_content_chars
        self._allow_private_outbound = allow_private_outbound
        self._allowed_hosts = allowed_hosts
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
        except URLPolicyError as exc:
            return f"Error: Page URL blocked by outbound URL policy: {exc}"
        except Exception as exc:
            logger.warning("Page fetch failed for host %s: %s", _safe_host(url), exc)
            return f"Error: Failed to fetch page: {exc}"

        if len(content) > self._max_content_chars:
            content = content[: self._max_content_chars]
            content += "\n\n[content truncated]"

        return "[UNTRUSTED_WEB_DATA]\n" + content

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
        validated = await validate_url_for_request(
            url,
            allow_private=self._allow_private_outbound,
            allowed_hosts=self._allowed_hosts,
        )
        # Service workers can issue requests that page routing does not expose.
        # Block them so every browser request remains covered by the URL policy.
        context = None
        new_context = getattr(self._browser, "new_context", None)
        if new_context is not None:
            context = await new_context(service_workers="block")
            page = await context.new_page()
        else:  # pragma: no cover - compatibility with lightweight test doubles
            page = await self._browser.new_page()
        route_handler = self._route_handler
        try:
            # Route every browser request, not only the initial navigation.
            # Public pages can embed images, scripts, or redirects targeting
            # loopback and private network addresses.
            route = getattr(page, "route", None)
            if route is not None:
                await route("**/*", route_handler)
            await page.goto(validated.value, timeout=int(self._timeout_seconds * 1000))
            raw = await page.evaluate("document.body.innerText")
            return str(raw) if raw is not None else ""
        finally:
            unroute = getattr(page, "unroute", None)
            if unroute is not None:
                try:
                    await unroute("**/*", route_handler)
                except Exception:
                    logger.debug("Failed to remove Playwright route", exc_info=True)
            await page.close()
            if context is not None:
                await context.close()

    async def _route_handler(self, route: Any) -> None:
        """Allow only validated public requests made by the browser."""
        request = getattr(route, "request", None)
        request_url = getattr(request, "url", "")
        try:
            await validate_url_for_request(
                request_url,
                allow_private=self._allow_private_outbound,
                allowed_hosts=self._allowed_hosts,
            )
        except URLPolicyError:
            await route.abort(error_code="blockedbyclient")
            return
        await route.continue_()


def _safe_host(url: str) -> str:
    """Return a host for logs without retaining a full potentially sensitive URL."""
    try:
        from urllib.parse import urlsplit

        return urlsplit(url).hostname or "unknown"
    except ValueError:
        return "unknown"
