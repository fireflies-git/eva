from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import discord
import pytest

import eva.discord.summarize_commands as summarize_commands
from eva.ai import AIClientError, SummarizationService
from eva.ai.schemas import ChatMessage
from eva.discord.summarize_commands import (
    handle_summarize_command,
    is_summarize_command,
)


class StubChatCompletionClient:
    def __init__(self, response: str = "summary") -> None:
        self.response = response
        self.calls: list[dict] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


class FailingChatCompletionClient:
    async def chat_completion(self, **kwargs: object) -> str:
        raise AIClientError("upstream down")


def _make_message() -> discord.Message:
    return cast(
        discord.Message,
        SimpleNamespace(
            id=1,
            channel=SimpleNamespace(),
            author=SimpleNamespace(id=42),
            reference=None,
        ),
    )


def test_is_summarize_command_recognizes_aliases() -> None:
    assert is_summarize_command(content="eva summarize", trigger_prefix="eva ") is True
    assert is_summarize_command(content="eva tldr 20", trigger_prefix="eva ") is True
    assert is_summarize_command(content="eva hello", trigger_prefix="eva ") is False
    assert is_summarize_command(content="other text", trigger_prefix="eva ") is False


def test_command_returns_unhandled_when_not_a_summarize_message(monkeypatch) -> None:
    response = asyncio.run(
        handle_summarize_command(
            message=_make_message(),
            content="eva hi",
            trigger_prefix="eva ",
            summarization_service=cast(
                SummarizationService,
                SummarizationService(client=StubChatCompletionClient(), model_name="m"),
            ),
        )
    )
    assert response.handled is False


def test_command_reports_missing_service() -> None:
    response = asyncio.run(
        handle_summarize_command(
            message=_make_message(),
            content="eva summarize",
            trigger_prefix="eva ",
            summarization_service=None,
        )
    )
    assert response.handled is True
    assert "not available" in response.content


def test_command_rejects_out_of_range(monkeypatch) -> None:
    async def fake_fetch(channel, *, limit, exclude_message_id=None):
        raise AssertionError("should not fetch when validation fails first")

    monkeypatch.setattr(summarize_commands, "fetch_channel_context", fake_fetch)
    response = asyncio.run(
        handle_summarize_command(
            message=_make_message(),
            content="eva summarize 9999",
            trigger_prefix="eva ",
            summarization_service=cast(
                SummarizationService,
                SummarizationService(client=StubChatCompletionClient(), model_name="m"),
            ),
        )
    )
    assert response.handled is True
    assert "between" in response.content


def test_command_rejects_non_numeric_argument(monkeypatch) -> None:
    async def fake_fetch(channel, *, limit, exclude_message_id=None):
        raise AssertionError("should not fetch when parsing fails")

    monkeypatch.setattr(summarize_commands, "fetch_channel_context", fake_fetch)
    response = asyncio.run(
        handle_summarize_command(
            message=_make_message(),
            content="eva summarize twelve",
            trigger_prefix="eva ",
            summarization_service=cast(
                SummarizationService,
                SummarizationService(client=StubChatCompletionClient(), model_name="m"),
            ),
        )
    )
    assert response.handled is True
    assert "Usage" in response.content


def test_command_returns_warning_when_no_messages(monkeypatch) -> None:
    async def fake_fetch(channel, *, limit, exclude_message_id=None):
        return []

    monkeypatch.setattr(summarize_commands, "fetch_channel_context", fake_fetch)
    response = asyncio.run(
        handle_summarize_command(
            message=_make_message(),
            content="eva summarize 10",
            trigger_prefix="eva ",
            summarization_service=cast(
                SummarizationService,
                SummarizationService(client=StubChatCompletionClient(), model_name="m"),
            ),
        )
    )
    assert response.handled is True
    assert "couldn't find" in response.content.lower()


def test_command_returns_summary(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_fetch(channel, *, limit, exclude_message_id=None):
        captured["limit"] = limit
        return cast(
            list[ChatMessage],
            [
                {"role": "user", "content": "[12:00] alice: hi"},
                {"role": "user", "content": "[12:01] bob: hello"},
            ],
        )

    monkeypatch.setattr(summarize_commands, "fetch_channel_context", fake_fetch)

    chat_client = StubChatCompletionClient(response="- alice and bob exchanged greetings")
    service = SummarizationService(client=chat_client, model_name="model-x")

    response = asyncio.run(
        handle_summarize_command(
            message=_make_message(),
            content="eva summarize 25",
            trigger_prefix="eva ",
            summarization_service=service,
            requester_context="requester: user(...)",
        )
    )

    assert response.handled is True
    assert "Summary of the last 2 messages" in response.content
    assert "alice and bob" in response.content
    assert captured["limit"] == 25
    assert chat_client.calls, "chat client should have been called"
    # The system prompt must be the first message.
    messages = cast(list[ChatMessage], chat_client.calls[0]["messages"])
    assert messages[0]["role"] == "system"
    assert "summariz" in messages[0]["content"].lower()


def test_command_reports_ai_failure(monkeypatch) -> None:
    async def fake_fetch(channel, *, limit, exclude_message_id=None):
        return [{"role": "user", "content": "[12:00] alice: hi"}]

    monkeypatch.setattr(summarize_commands, "fetch_channel_context", fake_fetch)
    service = SummarizationService(client=FailingChatCompletionClient(), model_name="m")

    response = asyncio.run(
        handle_summarize_command(
            message=_make_message(),
            content="eva summarize 10",
            trigger_prefix="eva ",
            summarization_service=service,
        )
    )
    assert response.handled is True
    assert "Couldn't summarize" in response.content


def test_service_rejects_empty_input() -> None:
    service = SummarizationService(client=StubChatCompletionClient(), model_name="m")
    with pytest.raises(AIClientError):
        asyncio.run(service.summarize(channel_messages=[]))


def test_command_uses_default_when_no_argument(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_fetch(channel, *, limit, exclude_message_id=None):
        captured["limit"] = limit
        return [{"role": "user", "content": "x"}]

    monkeypatch.setattr(summarize_commands, "fetch_channel_context", fake_fetch)
    service = SummarizationService(client=StubChatCompletionClient(), model_name="m")

    asyncio.run(
        handle_summarize_command(
            message=_make_message(),
            content="eva tldr",
            trigger_prefix="eva ",
            summarization_service=service,
        )
    )
    assert captured["limit"] == summarize_commands.DEFAULT_SUMMARIZE_MESSAGES
