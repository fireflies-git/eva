import asyncio

from eva.search.client import SerperClient


class StubSerperClient(SerperClient):
    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(api_key="test", timeout_seconds=30.0)
        self._payload = payload

    async def _request(self, query: str) -> dict[str, object]:
        return self._payload


def test_serper_client_normalizes_payload() -> None:
    client = StubSerperClient(
        {
            "answerBox": {
                "title": "Apple stock price",
                "answer": "$123",
                "link": "https://example.com/answer",
            },
            "knowledgeGraph": {
                "title": "Apple",
                "description": "Technology company",
                "descriptionSource": "Wikipedia",
                "descriptionLink": "https://example.com/wiki",
            },
            "organic": [
                {
                    "title": "Apple",
                    "link": "https://apple.com",
                    "snippet": "Official site",
                    "position": 1,
                    "date": "Today",
                }
            ],
        }
    )

    result = asyncio.run(client.search("apple inc"))

    assert result.query == "apple inc"
    assert result.answer_box is not None
    assert result.answer_box.answer == "$123"
    assert result.knowledge_graph is not None
    assert result.knowledge_graph.source == "Wikipedia"
    assert len(result.organic_results) == 1
    assert result.organic_results[0].link == "https://apple.com"


def test_serper_client_ignores_invalid_organic_results() -> None:
    client = StubSerperClient(
        {
            "organic": [
                {"title": "Missing fields"},
                {
                    "title": "Valid",
                    "link": "https://example.com",
                    "snippet": "Snippet",
                    "position": 1,
                },
            ]
        }
    )

    result = asyncio.run(client.search("example"))

    assert len(result.organic_results) == 1
    assert result.organic_results[0].title == "Valid"
