import asyncio
import logging

import pytest

from eva.ai import AIClientError
from eva.ai.respond import TOS_MODERATION_MAX_TOKENS, TOSCheckService, contains_underage_claim

MODERATION_MODEL = "test-moderation-model"


class StubModerationClient:
    def __init__(self, *, response: str | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response or ""


def test_tos_check_uses_configured_model() -> None:
    client = StubModerationClient(response="NO")
    service = TOSCheckService(client=client, model_name=MODERATION_MODEL)

    decision = asyncio.run(service.check_tos_violation("hello"))

    assert decision is False
    assert client.calls[0]["model"] == MODERATION_MODEL
    assert "allow_reasoning_fallback" not in client.calls[0]


def test_tos_check_leaves_token_room_for_reasoning_models() -> None:
    client = StubModerationClient(response="NO")
    service = TOSCheckService(client=client, model_name=MODERATION_MODEL)

    asyncio.run(service.check_tos_violation("hello"))

    # Reasoning models burn reasoning tokens from the same budget; a tiny
    # budget starves the verdict and silently fails open on empty output.
    assert client.calls[0]["max_tokens"] == TOS_MODERATION_MAX_TOKENS
    assert TOS_MODERATION_MAX_TOKENS >= 128


def test_tos_check_blocks_when_model_says_yes() -> None:
    client = StubModerationClient(response="YES")
    service = TOSCheckService(client=client, model_name=MODERATION_MODEL)

    decision = asyncio.run(service.check_tos_violation("some text"))

    assert decision is True


def test_tos_check_allows_when_model_output_unparseable(caplog) -> None:
    client = StubModerationClient(response="maybe")
    service = TOSCheckService(client=client, model_name=MODERATION_MODEL)

    with caplog.at_level(logging.WARNING):
        decision = asyncio.run(service.check_tos_violation("hello"))

    assert decision is False
    assert "TOS moderation returned unexpected response" in caplog.text


def test_tos_check_allows_reply_when_model_returns_empty_output(caplog) -> None:
    client = StubModerationClient(error=AIClientError("Model returned empty response content"))
    service = TOSCheckService(client=client, model_name=MODERATION_MODEL)

    with caplog.at_level(logging.DEBUG):
        decision = asyncio.run(service.check_tos_violation("hello"))

    assert decision is False
    assert "TOS moderation returned empty output; allowing reply" in caplog.text


@pytest.mark.parametrize(
    "text",
    [
        "i'm 10 years old",
        "im 12",
        "I am 9 y/o",
        "lol i'm a minor",
        "i'm underage",
        "i'm only 11",
        "i'm 12 yrs old",
    ],
)
def test_contains_underage_claim_blocks(text: str) -> None:
    assert contains_underage_claim(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "i'm 18",
        "i'm 13",
        "i'm 10/10 rn",
        "i'm 10.5/10 tbh",
        "she's 10",
        "i'm 100 percent sure",
        "hello",
    ],
)
def test_contains_underage_claim_allows(text: str) -> None:
    assert contains_underage_claim(text) is False


def test_check_tos_violation_blocks_underage_claim_without_ai_call() -> None:
    client = StubModerationClient(response="NO")
    service = TOSCheckService(client=client, model_name=MODERATION_MODEL)

    decision = asyncio.run(service.check_tos_violation("i'm 10 years old"))

    assert decision is True
    assert client.calls == []


def test_check_tos_violation_backstop_blocks_when_client_errors() -> None:
    client = StubModerationClient(error=AIClientError("Model API error HTTP 400"))
    service = TOSCheckService(client=client, model_name=MODERATION_MODEL)

    decision = asyncio.run(service.check_tos_violation("im 11"))

    assert decision is True
