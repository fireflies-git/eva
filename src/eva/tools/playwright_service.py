"""Web page fetch tool service using Playwright.

Fetches the visible text content of a URL via headless Chromium.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable
from typing import Any, cast

from eva.security.urls import URLPolicyError, validate_url_for_request

logger = logging.getLogger(__name__)

_AUTONOMOUS_TOOL_NAME = "fetch_web_page"
_MAX_REDIRECTS = 5


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
            logger.warning(
                "Page fetch failed for host %s error_type=%s",
                _safe_host(url),
                type(exc).__name__,
            )
            return "Error: Failed to fetch page"

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
        websocket_handler = self._websocket_handler
        request_route_target: Any = (
            context
            if context is not None and callable(getattr(context, "route", None))
            else page
        )
        websocket_route_target: Any = (
            context
            if context is not None
            and callable(getattr(context, "route_web_socket", None))
            else page
        )
        try:
            # Route at the browser-context level so popups and newly opened
            # pages receive the same policy as the initial page.
            route: Any = getattr(request_route_target, "route", None)
            if callable(route):
                await cast(Awaitable[Any], route("**/*", route_handler))
            route_web_socket: Any = getattr(
                websocket_route_target,
                "route_web_socket",
                None,
            )
            if callable(route_web_socket):
                await cast(
                    Awaitable[Any],
                    route_web_socket("**/*", websocket_handler),
                )
            await page.goto(validated.value, timeout=int(self._timeout_seconds * 1000))
            # Slice in the browser before transferring text back to Python so a
            # page with a massive DOM cannot allocate an unbounded response.
            raw = await page.evaluate(
                "maxChars => document.body ? document.body.innerText.slice(0, maxChars) : ''",
                self._max_content_chars + 1,
            )
            return str(raw) if raw is not None else ""
        finally:
            unroute: Any = getattr(request_route_target, "unroute", None)
            if callable(unroute):
                try:
                    await cast(Awaitable[Any], unroute("**/*", route_handler))
                except Exception:
                    logger.debug("Failed to remove Playwright route", exc_info=True)
            unroute_web_socket: Any = getattr(
                websocket_route_target,
                "unroute_web_socket",
                None,
            )
            if callable(unroute_web_socket):
                try:
                    await cast(
                        Awaitable[Any],
                        unroute_web_socket("**/*", websocket_handler),
                    )
                except Exception:
                    logger.debug("Failed to remove Playwright WebSocket route", exc_info=True)
            await page.close()
            if context is not None:
                await context.close()

    async def _route_handler(self, route: Any) -> None:
        """Allow only validated public requests made by the browser."""
        request = getattr(route, "request", None)
        request_url = getattr(request, "url", "")
        if _redirect_depth(request) > _MAX_REDIRECTS:
            await route.abort(error_code="blockedbyclient")
            return
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

    async def _websocket_handler(self, websocket: Any) -> None:
        """Block WebSocket connections so they cannot bypass request routing."""

        websocket_url = getattr(websocket, "url", "")
        try:
            await validate_url_for_request(
                websocket_url,
                allow_private=self._allow_private_outbound,
                allowed_hosts=self._allowed_hosts,
            )
        except URLPolicyError:
            await websocket.close(code=1008, reason="blocked by outbound URL policy")
            return

        # Public WebSockets are still unnecessary for extracting page text. A
        # fail-closed route avoids relying on a browser-specific connect API.
        await websocket.close(code=1008, reason="WebSockets are disabled")


def _safe_host(url: str) -> str:
    """Return a host for logs without retaining a full potentially sensitive URL."""
    try:
        from urllib.parse import urlsplit

        return urlsplit(url).hostname or "unknown"
    except ValueError:
        return "unknown"


def _redirect_depth(request: Any) -> int:
    """Count a request's redirect chain without trusting page content."""

    depth = 0
    seen: set[int] = set()
    current = request
    while current is not None:
        marker = id(current)
        if marker in seen:
            return _MAX_REDIRECTS + 1
        seen.add(marker)
        current = getattr(current, "redirected_from", None)
        if current is not None:
            depth += 1
        if depth > _MAX_REDIRECTS:
            break
    return depth
