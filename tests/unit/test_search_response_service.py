import asyncio

from eva.ai import SearchResponseService
from eva.search import SearchAnswerBox, SearchOrganicResult, SearchResultBundle


class FakeSearchResponseClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return "grounded answer"


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
        )
    )

    assert reply == "grounded answer"
    assert len(client.calls) == 1
    payload = client.calls[0]
    assert payload["messages"][0]["content"] == "search prompt"
    search_input = payload["messages"][1]["content"]
    assert "Result 5" in search_input
    assert "Result 6" not in search_input
