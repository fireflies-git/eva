import asyncio

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


class DummyChannel:
    pass


class DummyClient:
    pass


def test_reply_generation_uses_normal_path_when_search_not_needed() -> None:
    response_service = StubResponseService("normal")
    reply_service = ReplyGenerationService(
        response_service=response_service,
        search_service=StubSearchService(result=None),
        search_response_service=StubSearchResponseService("search"),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=DummyChannel(),
            client=DummyClient(),
            context_messages=[],
            history_messages=[],
            user_message="hello there",
            reply_context=None,
        )
    )

    assert reply == "normal"
    assert len(response_service.calls) == 1


def test_reply_generation_uses_search_path_when_results_exist() -> None:
    response_service = StubResponseService("normal")
    search_response_service = StubSearchResponseService("search")
    reply_service = ReplyGenerationService(
        response_service=response_service,
        search_service=StubSearchService(result=SearchResultBundle(query="apple")),
        search_response_service=search_response_service,
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=DummyChannel(),
            client=DummyClient(),
            context_messages=[],
            history_messages=[],
            user_message="apple stock price today",
            reply_context=None,
        )
    )

    assert reply == "search"
    assert len(search_response_service.calls) == 1
    assert response_service.calls == []


def test_reply_generation_fails_closed_when_search_errors() -> None:
    reply_service = ReplyGenerationService(
        response_service=StubResponseService("normal"),
        search_service=StubSearchService(error=SearchClientError("boom")),
        search_response_service=StubSearchResponseService("search"),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=DummyChannel(),
            client=DummyClient(),
            context_messages=[],
            history_messages=[],
            user_message="latest apple stock price",
            reply_context=None,
        )
    )

    assert reply == SEARCH_FAILURE_MESSAGE
