import asyncio
from typing import cast

import discord

from eva.ai.orchestrator import SEARCH_FAILURE_MESSAGE, ReplyGenerationService
from eva.search import SearchClientError, SearchResultBundle


class StubResponseService:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


class StubSearchService:
    def __init__(
        self,
        *,
        result: SearchResultBundle | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error

    async def search_if_needed(self, **kwargs: object) -> SearchResultBundle | None:
        if self.error is not None:
            raise self.error
        return self.result


class StubSearchResponseService:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


class StubTOSCheckService:
    def __init__(self, *, is_violation: bool = False) -> None:
        self.is_violation = is_violation
        self.calls: list[str] = []

    async def check_tos_violation(self, text: str) -> bool:
        self.calls.append(text)
        return self.is_violation


class DummyChannel:
    pass


class DummyClient:
    pass


def test_reply_generation_uses_normal_path_when_search_not_needed() -> None:
    response_service = StubResponseService("normal")
    tos_service = StubTOSCheckService()
    reply_service = ReplyGenerationService(
        response_service=response_service,
        search_service=StubSearchService(result=None),
        search_response_service=StubSearchResponseService("search"),
        tos_check_service=tos_service,
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="hello there",
            reply_context=None,
        )
    )

    assert reply == "normal"
    assert len(response_service.calls) == 1
    assert tos_service.calls == ["normal"]


def test_reply_generation_uses_search_path_when_results_exist() -> None:
    response_service = StubResponseService("normal")
    search_response_service = StubSearchResponseService("search")
    tos_service = StubTOSCheckService()
    reply_service = ReplyGenerationService(
        response_service=response_service,
        search_service=StubSearchService(result=SearchResultBundle(query="apple")),
        search_response_service=search_response_service,
        tos_check_service=tos_service,
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="apple stock price today",
            reply_context=None,
        )
    )

    assert reply == "search"
    assert len(search_response_service.calls) == 1
    assert response_service.calls == []
    assert tos_service.calls == ["search"]


def test_reply_generation_fails_closed_when_search_errors() -> None:
    reply_service = ReplyGenerationService(
        response_service=StubResponseService("normal"),
        search_service=StubSearchService(error=SearchClientError("boom")),
        search_response_service=StubSearchResponseService("search"),
        tos_check_service=StubTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="latest apple stock price",
            reply_context=None,
        )
    )

    assert reply == SEARCH_FAILURE_MESSAGE


def test_reply_generation_blocks_tos_violations() -> None:
    reply_service = ReplyGenerationService(
        response_service=StubResponseService("normal"),
        search_service=StubSearchService(result=None),
        search_response_service=StubSearchResponseService("search"),
        tos_check_service=StubTOSCheckService(is_violation=True),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="hello there",
            reply_context=None,
        )
    )

    assert "violates my safety or TOS guidelines" in reply
