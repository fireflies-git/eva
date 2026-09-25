from __future__ import annotations

import asyncio

import pytest

from eva.tools.playwright_service import PlaywrightService


class FakeWebSocketRoute:
    def __init__(self, url: str) -> None:
        self.url = url
        self.close_calls: list[tuple[int, str]] = []

    async def close(self, *, code: int, reason: str) -> None:
        self.close_calls.append((code, reason))


class FakeRequest:
    def __init__(self, url: str) -> None:
        self.url = url


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
