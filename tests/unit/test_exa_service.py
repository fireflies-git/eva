from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import aiohttp
import pytest

from eva.tools import ToolService
from eva.tools.exa_service import ExaService, _read_response_body


class FakeContent:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def iter_chunked(self, size: int):
        for start in range(0, len(self._body), size):
            yield self._body[start : start + size]


class FakeResponse:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.charset = "utf-8"
        self.content = FakeContent(body)

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeSession:
    def __init__(self, response: FakeResponse | Exception) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _service(session: FakeSession | None, *, max_results: int = 5) -> ExaService:
    service = ExaService(api_key="secret", max_results=max_results, allow_private_outbound=True)
    service._session = cast(aiohttp.ClientSession | None, session)
    return service


def _run(service: ExaService, arguments: dict[str, Any] | str) -> str:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return asyncio.run(service.run_autonomous_tool(raw))


def test_conforms_to_tool_service_protocol() -> None:
    service = _service(None)

    assert isinstance(service, ToolService)
    assert service.autonomous_tool_name == "web_search"
    function = cast(dict[str, Any], service.build_autonomous_tool_definition()["function"])
    assert function["parameters"]["required"] == ["query", "objective"]


def test_search_sends_recommended_request_and_formats_results() -> None:
    body = json.dumps(
        {
            "results": [
                {
                    "title": "Release notes",
                    "url": "https://example.com/a",
                    "publishedDate": "2026-01-02",
                    "highlights": ["first   line\nsecond", " "],
                },
                {"url": "https://example.com/b"},
                {"title": "no url"},
                "junk",
            ]
        }
    ).encode()
    session = FakeSession(FakeResponse(200, body))

    result = _run(_service(session), {"query": "python news", "objective": "find releases"})

    call = session.calls[0]
    assert call["url"] == "https://api.exa.ai/search"
    assert call["headers"]["x-api-key"] == "secret"
    assert call["allow_redirects"] is False
    assert call["json"] == {
        "query": "python news",
        "type": "auto",
        "contents": {"highlights": True},
        "objective": "find releases",
    }
    assert result.startswith("[UNTRUSTED_WEB_DATA]\n")
    assert "1. Release notes\n   URL: https://example.com/a" in result
    assert "Published: 2026-01-02" in result
    assert "first line second" in result
    assert "2. https://example.com/b" in result
    assert "no url" not in result


def test_objective_is_omitted_when_blank() -> None:
    session = FakeSession(FakeResponse(200, b'{"results": []}'))

    _run(_service(session), {"query": "x", "objective": "  "})

    assert "objective" not in session.calls[0]["json"]


def test_results_are_capped() -> None:
    results = [{"title": f"t{i}", "url": f"https://example.com/{i}"} for i in range(10)]
    session = FakeSession(FakeResponse(200, json.dumps({"results": results}).encode()))

    result = _run(_service(session, max_results=2), {"query": "x", "objective": "y"})

    assert "2. t1" in result
    assert "3. " not in result


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ("not json", "valid JSON"),
        ("[]", "JSON object"),
        ({"objective": "y"}, '"query"'),
        ({"query": "  ", "objective": "y"}, '"query"'),
    ],
)
def test_invalid_arguments_are_rejected(arguments: dict[str, Any] | str, expected: str) -> None:
    session = FakeSession(FakeResponse(200, b"{}"))

    assert expected in _run(_service(session), arguments)
    assert session.calls == []


def test_not_started_service_reports_error() -> None:
    assert "not started" in _run(_service(None), {"query": "x", "objective": "y"})


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(500, b"{}"),
        FakeResponse(200, b"not json"),
        FakeResponse(200, b"[]"),
        aiohttp.ClientError("boom"),
        TimeoutError(),
    ],
)
def test_failures_return_generic_error_without_leaking_details(
    response: FakeResponse | Exception,
) -> None:
    result = _run(_service(FakeSession(response)), {"query": "x", "objective": "y"})

    assert result == "Error: Web search failed."


def test_empty_results_message() -> None:
    session = FakeSession(FakeResponse(200, b'{"results": []}'))

    assert (
        _run(_service(session), {"query": "x", "objective": "y"}) == "No web search results found."
    )


def test_response_body_cap_rejects_oversized_payload() -> None:
    response = FakeResponse(200, b"x" * 100)

    with pytest.raises(RuntimeError, match="size limit"):
        asyncio.run(_read_response_body(response, max_bytes=10))
