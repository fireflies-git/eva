import asyncio
import logging

from eva.ai import AIClientError
from eva.ai.respond import TOS_MODERATION_MODEL, TOSCheckService


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


def test_tos_check_disables_reasoning_fallback() -> None:
    client = StubModerationClient(response="NO")
    service = TOSCheckService(client=client)

    decision = asyncio.run(service.check_tos_violation("hello"))

    assert decision is False
    assert "allow_reasoning_fallback" not in client.calls[0]
    assert client.calls[0]["model"] == TOS_MODERATION_MODEL


def test_tos_check_allows_reply_when_model_returns_empty_output(caplog) -> None:
    client = StubModerationClient(error=AIClientError("Model returned empty response content"))
    service = TOSCheckService(client=client)

    with caplog.at_level(logging.DEBUG):
        decision = asyncio.run(service.check_tos_violation("hello"))

    assert decision is False
    assert "TOS moderation returned empty output; allowing reply" in caplog.text
