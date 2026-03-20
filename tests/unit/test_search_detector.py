import asyncio

from eva.ai import AIClientError
from eva.search import SearchDetector


class FakeDetectorClient:
    def __init__(self, *, response: str = "NO", should_fail: bool = False) -> None:
        self.response = response
        self.should_fail = should_fail
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if self.should_fail:
            raise AIClientError("detector failed")
        return self.response


def test_search_detector_triggers_for_current_lookup() -> None:
    decision = asyncio.run(
        SearchDetector(client=FakeDetectorClient(response="YES"), model_name="model").should_search(
            "what is the latest Python 3.12 release"
        )
    )
    assert decision.should_search is True


def test_search_detector_triggers_for_world_superlative_question() -> None:
    decision = asyncio.run(
        SearchDetector(client=FakeDetectorClient(response="YES"), model_name="model").should_search(
            "who is the oldest person in the world rn"
        )
    )
    assert decision.should_search is True


def test_search_detector_triggers_for_person_superlative_question() -> None:
    decision = asyncio.run(
        SearchDetector(client=FakeDetectorClient(response="YES"), model_name="model").should_search(
            "who is the oldest person rn"
        )
    )
    assert decision.should_search is True


def test_search_detector_does_not_trigger_for_creative_prompt() -> None:
    decision = asyncio.run(
        SearchDetector(client=FakeDetectorClient(response="NO"), model_name="model").should_search(
            "write a poem about apples"
        )
    )
    assert decision.should_search is False


def test_search_detector_does_not_trigger_for_channel_question() -> None:
    decision = asyncio.run(
        SearchDetector(client=FakeDetectorClient(response="NO"), model_name="model").should_search(
            "who said that in this chat"
        )
    )
    assert decision.should_search is False


def test_search_detector_rejects_ambiguous_model_output() -> None:
    decision = asyncio.run(
        SearchDetector(
            client=FakeDetectorClient(response="NO, unless it needs search"),
            model_name="model",
        ).should_search("apple stock price")
    )

    assert decision.should_search is False
    assert decision.reason == "ai-invalid"


def test_search_detector_falls_back_closed_on_ai_error() -> None:
    decision = asyncio.run(
        SearchDetector(
            client=FakeDetectorClient(should_fail=True),
            model_name="model",
        ).should_search("apple stock price")
    )

    assert decision.should_search is False
    assert decision.reason == "ai-error"
