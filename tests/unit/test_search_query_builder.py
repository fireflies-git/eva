import asyncio

from eva.ai import AIClientError
from eva.search import SearchQueryBuilder


class FakeQueryClient:
    def __init__(self, *, response: str = "", should_fail: bool = False) -> None:
        self.response = response
        self.should_fail = should_fail
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if self.should_fail:
            raise AIClientError("rewrite failed")
        return self.response


def test_search_query_builder_returns_explicit_message_without_rewrite() -> None:
    client = FakeQueryClient(response="ignored")
    builder = SearchQueryBuilder(client=client, model_name="model")

    query = asyncio.run(
        builder.build_query(
            user_message="latest python 3.12 release date",
            recent_context=[],
            reply_context=None,
        )
    )

    assert query == "latest python 3.12 release date"
    assert client.calls == []


def test_search_query_builder_uses_context_for_referential_message() -> None:
    client = FakeQueryClient(response="Apple Inc stock price today")
    builder = SearchQueryBuilder(client=client, model_name="model")

    query = asyncio.run(
        builder.build_query(
            user_message="what about today",
            recent_context=[
                {"role": "user", "content": "[10:00] Neo: Apple Inc stock price"},
                {"role": "user", "content": "[10:01] Neo: can you check it"},
            ],
            reply_context=None,
        )
    )

    assert query == "Apple Inc stock price today"
    assert len(client.calls) == 1


def test_search_query_builder_falls_back_when_rewrite_fails() -> None:
    client = FakeQueryClient(should_fail=True)
    builder = SearchQueryBuilder(client=client, model_name="model")

    query = asyncio.run(
        builder.build_query(
            user_message="what about that",
            recent_context=[],
            reply_context="Neo: Apple Inc stock price",
        )
    )

    assert query == "what about that"
