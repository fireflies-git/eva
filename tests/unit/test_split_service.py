import asyncio

from eva.ai.splitting import ResponseSplitService


class StubClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


def test_response_split_service_uses_override_model_and_parses_json() -> None:
    client = StubClient('{"messages":["first paragraph","second paragraph"]}')
    service = ResponseSplitService(client=client, model_name="llama3.3-70b-instruct")

    result = asyncio.run(
        service.split_reply(
            reply_content="first paragraph\n\nsecond paragraph",
            first_limit=100,
            continuation_limit=100,
        )
    )

    assert result == ["first paragraph", "second paragraph"]
    assert client.calls[0]["model"] == "llama3.3-70b-instruct"


def test_response_split_service_rejects_altered_content() -> None:
    client = StubClient('{"messages":["first paragraph","rewritten paragraph"]}')
    service = ResponseSplitService(client=client, model_name="llama3.3-70b-instruct")

    result = asyncio.run(
        service.split_reply(
            reply_content="first paragraph\n\nsecond paragraph",
            first_limit=100,
            continuation_limit=100,
        )
    )

    assert result is None
