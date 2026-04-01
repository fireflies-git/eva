import asyncio
from typing import Any, cast

from eva.ai import SearchResponseService
from eva.ai.client import StoredResponseOutput
from eva.search import SearchAnswerBox, SearchOrganicResult, SearchResultBundle


class FakeSearchResponseClient:
    def __init__(self) -> None:
        self.response_calls: list[dict[str, object]] = []
        self.chat_calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.chat_calls.append(kwargs)
        return "grounded answer"

    async def create_response(self, **kwargs: object) -> StoredResponseOutput:
        self.response_calls.append(kwargs)
        return StoredResponseOutput(response_id="resp-search", content="grounded answer")


def test_search_response_service_uses_search_prompt_and_limits_results() -> None:
    client = FakeSearchResponseClient()
    service = SearchResponseService(client=client, model_name="model")
    results = SearchResultBundle(
        query="apple stock price today",
        answer_box=SearchAnswerBox(
            title="Apple stock price",
            answer="$123",
            link="https://example.com/answer",
        ),
        organic_results=[
            SearchOrganicResult(
                title=f"Result {index}",
                link=f"https://example.com/{index}",
                snippet=f"Snippet {index}",
                position=index,
            )
            for index in range(1, 7)
        ],
    )

    reply = asyncio.run(
        service.generate_reply(
            system_prompt="search prompt",
            search_results=results,
            recent_context=[],
            user_message="what is apple stock price today",
            reply_context=None,
            requester_context=None,
        )
    )

    assert reply.content == "grounded answer"
    assert reply.response_id == "resp-search"
    assert client.chat_calls == []
    assert len(client.response_calls) == 1
    payload = client.response_calls[0]
    messages = cast(list[dict[str, Any]], payload["messages"])
    search_input = cast(str, messages[0]["content"])
    assert "Result 5" in search_input
    assert "Result 6" not in search_input
