from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from eva.tools.playwright_service import PlaywrightService


class FakeWebSocketRoute:
    def __init__(self, url: str) -> None:
        self.url = url
        self.close_calls: list[tuple[int, str]] = []

    async def close(self, *, code: int, reason: str) -> None:
        self.close_calls.append((code, reason))


class FakeRequest:
    def __init__(self, url: str, redirected_from: FakeRequest | None = None) -> None:
        self.url = url
        self.redirected_from = redirected_from


class FakeRequestRoute:
    def __init__(self, url: str) -> None:
        self.request = FakeRequest(url)
        self.abort_calls: list[str] = []
        self.continue_calls = 0

    async def abort(self, *, error_code: str) -> None:
        self.abort_calls.append(error_code)

    async def continue_(self) -> None:
        self.continue_calls += 1


def test_browser_blocks_private_websocket_requests() -> None:
    service = PlaywrightService()
    route = FakeWebSocketRoute("ws://127.0.0.1/internal")

    asyncio.run(service._websocket_handler(route))

    assert route.close_calls == [(1008, "blocked by outbound URL policy")]


def test_browser_disables_public_websockets_for_text_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PlaywrightService()
    route = FakeWebSocketRoute("wss://example.com/socket")

    async def allow_public_url(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "eva.tools.playwright_service.validate_url_for_request",
        allow_public_url,
    )

    asyncio.run(service._websocket_handler(route))

    assert route.close_calls == [(1008, "WebSockets are disabled")]


def test_browser_route_blocks_private_subresources() -> None:
    service = PlaywrightService()
    route = FakeRequestRoute("http://127.0.0.1/admin")

    asyncio.run(service._route_handler(route))

    assert route.abort_calls == ["blockedbyclient"]
    assert route.continue_calls == 0


def test_browser_route_continues_validated_public_subresources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PlaywrightService()
    route = FakeRequestRoute("https://example.com/static/app.js")

    async def allow_public_url(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "eva.tools.playwright_service.validate_url_for_request",
        allow_public_url,
    )

    asyncio.run(service._route_handler(route))

    assert route.abort_calls == []
    assert route.continue_calls == 1


def test_browser_route_caps_redirect_chains() -> None:
    service = PlaywrightService()
    request = FakeRequest("https://example.com/6")
    for index in range(5, -1, -1):
        request = FakeRequest(f"https://example.com/{index}", redirected_from=request)
    route = FakeRequestRoute(request.url)
    route.request = request

    asyncio.run(service._route_handler(route))

    assert route.abort_calls == ["blockedbyclient"]
    assert route.continue_calls == 0


class _FakeBrowserContext:
    def __init__(self) -> None:
        self.page = _FakePage()
        self.route_calls: list[str] = []
        self.websocket_route_calls: list[str] = []
        self.unroute_calls: list[str] = []
        self.unroute_websocket_calls: list[str] = []
        self.closed = False

    async def new_page(self) -> _FakePage:
        return self.page

    async def route(self, pattern: str, _handler: object) -> None:
        self.route_calls.append(pattern)

    async def route_web_socket(self, pattern: str, _handler: object) -> None:
        self.websocket_route_calls.append(pattern)

    async def unroute(self, pattern: str, _handler: object) -> None:
        self.unroute_calls.append(pattern)

    async def unroute_web_socket(self, pattern: str, _handler: object) -> None:
        self.unroute_websocket_calls.append(pattern)

    async def close(self) -> None:
        self.closed = True


class _FakePage:
    async def goto(self, _url: str, *, timeout: int) -> None:
        assert timeout > 0

    async def evaluate(self, _script: str, _max_chars: int) -> str:
        return "page text"

    async def close(self) -> None:
        return None


class _FakeBrowser:
    def __init__(self) -> None:
        self.context = _FakeBrowserContext()

    async def new_context(self, *, service_workers: str) -> _FakeBrowserContext:
        assert service_workers == "block"
        return self.context


def test_browser_routes_at_context_level_for_popup_coverage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PlaywrightService()
    browser = _FakeBrowser()
    service._browser = browser

    async def allow_public_url(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(value="https://example.com")

    monkeypatch.setattr(
        "eva.tools.playwright_service.validate_url_for_request",
        allow_public_url,
    )

    assert asyncio.run(service._fetch_page("https://example.com")) == "page text"
    assert browser.context.route_calls == ["**/*"]
    assert browser.context.websocket_route_calls == ["**/*"]
    assert browser.context.unroute_calls == ["**/*"]
    assert browser.context.unroute_websocket_calls == ["**/*"]
    assert browser.context.closed is True
