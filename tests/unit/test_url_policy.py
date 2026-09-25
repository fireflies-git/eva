import asyncio
import socket

import pytest

from eva.security.urls import (
    PolicyResolver,
    URLPolicyError,
    validate_url,
    validate_url_for_request,
)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://localhost/admin",
        "http://127.0.0.1:8080/",
        "http://[::1]/",
        "https://user:password@example.com/",
        "https://example.com:99999/",
    ],
)
def test_validate_url_rejects_unsafe_syntax(url: str) -> None:
    with pytest.raises(URLPolicyError):
        validate_url(url)


def test_validate_url_accepts_public_http_url() -> None:
    validated = validate_url(" https://Example.com/articles#intro ")

    assert validated.hostname == "example.com"
    assert validated.value == "https://Example.com/articles#intro"


def test_validate_url_for_request_rejects_private_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("10.0.0.5", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(URLPolicyError, match="private"):
        asyncio.run(validate_url_for_request("https://example.com/"))


def test_validate_url_for_request_accepts_global_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    validated = asyncio.run(validate_url_for_request("https://example.com/"))
    assert validated.hostname == "example.com"


def test_policy_resolver_rejects_private_answer_at_connection_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(URLPolicyError, match="private"):
        asyncio.run(PolicyResolver().resolve("rebound.example", 443, socket.AF_INET))


def test_policy_resolver_returns_numeric_global_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    results = asyncio.run(PolicyResolver().resolve("example.com", 443, socket.AF_INET))
    assert results[0]["host"] == "93.184.216.34"
    assert results[0]["port"] == 443
