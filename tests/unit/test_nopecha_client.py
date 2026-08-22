from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import aiohttp
import discord
import pytest

from eva.captcha import NopeCHAClient, NopeCHAError
from eva.captcha.nopecha import _build_job_payload

_TOKEN_URL = "https://api.nopecha.com/token"
_CAPTCHA_URL = "https://discord.com"


def _captcha(
    *,
    service: str,
    sitekey: str | None = None,
    rqdata: str | None = None,
) -> discord.CaptchaRequired:
    exception = cast(Any, discord.CaptchaRequired.__new__(discord.CaptchaRequired))
    exception.service = service
    exception._sitekey = sitekey
    exception.errors = []
    exception.session_id = None
    exception.rqdata = rqdata
    exception.rqtoken = None
    exception.should_serve_invisible = False
    return cast(discord.CaptchaRequired, exception)


class FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._payload = payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    async def text(self) -> str:
        return json.dumps(self._payload)

    async def json(self) -> object:
        return self._payload


class FakeSession:
    def __init__(self) -> None:
        self.post_responses: list[FakeResponse] = []
        self.get_responses: list[FakeResponse] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []
        self.get_calls: list[tuple[str, dict[str, str]]] = []

    def post(
        self,
        url: str,
        json: dict[str, Any] | None = None,
        **kwargs: object,
    ) -> FakeResponse:
        self.post_calls.append((url, json or {}))
        if self.post_responses:
            return self.post_responses.pop(0)
        return FakeResponse(200, {})

    def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        **kwargs: object,
    ) -> FakeResponse:
        self.get_calls.append((url, params or {}))
        if self.get_responses:
            return self.get_responses.pop(0)
        # Unqueued polls keep returning "not solved yet" (used by timeout tests).
        return FakeResponse(200, {})


def _client_with_session(session: FakeSession, **kwargs: Any) -> NopeCHAClient:
    client = NopeCHAClient(**kwargs)
    client._session = cast(aiohttp.ClientSession, session)
    return client


# --- service / task mapping ---


def test_hcaptcha_maps_service_and_sitekey() -> None:
    payload = _build_job_payload(
        _captcha(service="hcaptcha", sitekey="sk123"),
        api_key=None,
    )

    assert payload == {
        "type": "hcaptcha",
        "task": {"sitekey": "sk123", "url": _CAPTCHA_URL},
    }


def test_hcaptcha_includes_rqdata_when_present() -> None:
    payload = _build_job_payload(
        _captcha(service="hcaptcha", sitekey="sk", rqdata="rd"),
        api_key=None,
    )

    assert payload["task"]["rqdata"] == "rd"


def test_hcaptcha_omits_rqdata_when_absent() -> None:
    payload = _build_job_payload(
        _captcha(service="hcaptcha", sitekey="sk"),
        api_key=None,
    )

    assert "rqdata" not in payload["task"]


def test_recaptcha_maps_to_recaptcha2() -> None:
    payload = _build_job_payload(
        _captcha(service="recaptcha", sitekey="sk"),
        api_key=None,
    )

    assert payload == {
        "type": "recaptcha2",
        "task": {"sitekey": "sk", "url": _CAPTCHA_URL},
    }


def test_recaptcha_enterprise_maps_to_recaptcha2_with_enterprise_flag() -> None:
    payload = _build_job_payload(
        _captcha(service="recaptcha_enterprise", sitekey="sk"),
        api_key=None,
    )

    assert payload["type"] == "recaptcha2"
    assert payload["task"]["enterprise"] is True


def test_unsupported_service_raises() -> None:
    with pytest.raises(NopeCHAError, match="Unsupported captcha service"):
        _build_job_payload(_captcha(service="mystery"), api_key=None)


def test_api_key_included_when_provided() -> None:
    payload = _build_job_payload(
        _captcha(service="hcaptcha", sitekey="sk"),
        api_key="key123",
    )

    assert payload["key"] == "key123"


def test_api_key_omitted_for_free_tier() -> None:
    payload = _build_job_payload(
        _captcha(service="hcaptcha", sitekey="sk"),
        api_key=None,
    )

    assert "key" not in payload


# --- job flow ---


def test_solve_posts_job_and_polls_until_solution() -> None:
    session = FakeSession()
    session.post_responses.append(FakeResponse(200, {"data": "job-1"}))
    session.get_responses.append(FakeResponse(200, {"data": None}))
    session.get_responses.append(FakeResponse(200, {"data": "SOLVED"}))

    client = _client_with_session(
        session,
        api_key=None,
        poll_interval_seconds=0.01,
        timeout_seconds=5.0,
    )
    solution = asyncio.run(client.solve(_captcha(service="hcaptcha", sitekey="sk")))

    assert solution == "SOLVED"
    assert session.post_calls[0][0] == _TOKEN_URL
    assert session.post_calls[0][1] == {
        "type": "hcaptcha",
        "task": {"sitekey": "sk", "url": _CAPTCHA_URL},
    }
    assert session.get_calls[0][1] == {"id": "job-1"}
    assert session.get_calls[1][1] == {"id": "job-1"}


def test_poll_includes_api_key_when_configured() -> None:
    session = FakeSession()
    session.post_responses.append(FakeResponse(200, {"data": "job-1"}))
    session.get_responses.append(FakeResponse(200, {"data": "SOLVED"}))

    client = _client_with_session(
        session,
        api_key="key123",
        poll_interval_seconds=0.01,
        timeout_seconds=5.0,
    )
    asyncio.run(client.solve(_captcha(service="hcaptcha", sitekey="sk")))

    assert session.post_calls[0][1]["key"] == "key123"
    assert session.get_calls[0][1] == {"id": "job-1", "key": "key123"}


def test_handle_captcha_entry_point_forwards_to_solve() -> None:
    session = FakeSession()
    session.post_responses.append(FakeResponse(200, {"data": "job-1"}))
    session.get_responses.append(FakeResponse(200, {"data": "SOLVED"}))

    client = _client_with_session(
        session,
        poll_interval_seconds=0.01,
        timeout_seconds=5.0,
    )
    solution = asyncio.run(
        client.handle_captcha(
            _captcha(service="hcaptcha", sitekey="sk"),
            cast(discord.Client, object()),
        )
    )

    assert solution == "SOLVED"


def test_no_credit_raises_nopecha_error() -> None:
    session = FakeSession()
    session.post_responses.append(FakeResponse(400, {"error": "no credit"}))

    client = _client_with_session(session, api_key="key")
    with pytest.raises(NopeCHAError, match="no credit"):
        asyncio.run(client.solve(_captcha(service="hcaptcha", sitekey="sk")))


def test_banned_ip_raises_nopecha_error() -> None:
    session = FakeSession()
    session.post_responses.append(FakeResponse(403, {"error": "banned user"}))

    client = _client_with_session(session)
    with pytest.raises(NopeCHAError, match="banned this IP"):
        asyncio.run(client.solve(_captcha(service="hcaptcha", sitekey="sk")))


def test_poll_timeout_raises_nopecha_error() -> None:
    session = FakeSession()
    session.post_responses.append(FakeResponse(200, {"data": "job-1"}))
    session.get_responses.append(FakeResponse(200, {"data": None}))

    client = _client_with_session(
        session,
        timeout_seconds=0.05,
        poll_interval_seconds=0.01,
    )
    with pytest.raises(NopeCHAError, match="timed out"):
        asyncio.run(client.solve(_captcha(service="hcaptcha", sitekey="sk")))


def test_solve_requires_started_session() -> None:
    client = NopeCHAClient()
    with pytest.raises(NopeCHAError, match="not started"):
        asyncio.run(client.solve(_captcha(service="hcaptcha", sitekey="sk")))
