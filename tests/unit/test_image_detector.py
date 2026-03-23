import asyncio

from eva.ai import AIClientError
from eva.images import ImageDetector


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


def test_image_detector_triggers_for_explicit_image_request() -> None:
    decision = asyncio.run(
        ImageDetector(
            client=FakeDetectorClient(response="YES"), model_name="model"
        ).should_generate("generate an image of a cinematic red fox in neon rain")
    )
    assert decision.should_generate is True


def test_image_detector_does_not_trigger_for_text_question() -> None:
    decision = asyncio.run(
        ImageDetector(client=FakeDetectorClient(response="NO"), model_name="model").should_generate(
            "what is the capital of france"
        )
    )
    assert decision.should_generate is False


def test_image_detector_rejects_ambiguous_model_output() -> None:
    decision = asyncio.run(
        ImageDetector(
            client=FakeDetectorClient(response="YES, generate one"),
            model_name="model",
        ).should_generate("draw a cat")
    )

    assert decision.should_generate is False
    assert decision.reason == "ai-invalid"


def test_image_detector_falls_back_closed_on_ai_error() -> None:
    decision = asyncio.run(
        ImageDetector(
            client=FakeDetectorClient(should_fail=True),
            model_name="model",
        ).should_generate("generate an image")
    )

    assert decision.should_generate is False
    assert decision.reason == "ai-error"
