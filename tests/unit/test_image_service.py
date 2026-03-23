import asyncio
from typing import cast

from eva.images import (
    GeneratedImage,
    ImageClient,
    ImageClientError,
    ImageDecision,
    ImageDetector,
    ImageGenerationService,
    ImageResultBundle,
)


class FakeDetector:
    def __init__(self, *, should_generate: bool = True) -> None:
        self._should_generate = should_generate
        self.calls: list[dict[str, object]] = []

    async def should_generate(self, *args: object, **kwargs: object) -> ImageDecision:
        self.calls.append({"args": args, "kwargs": kwargs})
        return ImageDecision(should_generate=self._should_generate)


class FakeImageClient:
    def __init__(
        self,
        *,
        result: ImageResultBundle,
        download_results: dict[str, tuple[bytes, str | None, str] | Exception] | None = None,
    ) -> None:
        self.result = result
        self.download_results = download_results or {}
        self.generate_calls: list[dict[str, object]] = []
        self.download_calls: list[dict[str, object]] = []

    async def generate(self, **kwargs: object) -> ImageResultBundle:
        self.generate_calls.append(kwargs)
        return self.result

    async def download_asset(
        self,
        *,
        url: str,
        filename_hint: str = "eva-image",
        max_bytes: int,
    ) -> tuple[bytes, str | None, str]:
        self.download_calls.append(
            {
                "url": url,
                "filename_hint": filename_hint,
                "max_bytes": max_bytes,
            }
        )
        outcome = self.download_results.get(url)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            raise ImageClientError("missing download fixture")
        return outcome


def test_image_generation_service_uses_plain_prompt_for_standalone_request() -> None:
    client = FakeImageClient(
        result=ImageResultBundle(
            images=[GeneratedImage(url="https://example.com/fox.png")],
        ),
        download_results={
            "https://example.com/fox.png": (b"fox", "image/png", "fox.png"),
        },
    )
    service = ImageGenerationService(
        client=cast(ImageClient, client),
        detector=cast(ImageDetector, FakeDetector()),
        model_name="model",
        language="en-US",
        incognito=True,
    )

    asyncio.run(
        service.generate_if_needed(
            user_message="generate an image of a neon fox in the rain",
            recent_context=[],
            reply_context=None,
        )
    )

    assert client.generate_calls[0]["prompt"] == "generate an image of a neon fox in the rain"


def test_image_generation_service_uses_reply_context_for_referential_follow_up() -> None:
    client = FakeImageClient(
        result=ImageResultBundle(
            images=[GeneratedImage(url="https://example.com/blue-fox.png")],
        ),
        download_results={
            "https://example.com/blue-fox.png": (b"fox", "image/png", "blue-fox.png"),
        },
    )
    service = ImageGenerationService(
        client=cast(ImageClient, client),
        detector=cast(ImageDetector, FakeDetector()),
        model_name="model",
        language="en-US",
        incognito=True,
    )

    asyncio.run(
        service.generate_if_needed(
            user_message="make it blue and more cinematic",
            recent_context=[],
            reply_context="A red fox standing in neon rain",
        )
    )

    prompt = client.generate_calls[0]["prompt"]
    assert isinstance(prompt, str)
    assert "Referenced content:" in prompt
    assert "A red fox standing in neon rain" in prompt
    assert "make it blue and more cinematic" in prompt


def test_image_generation_service_downloads_multiple_assets() -> None:
    client = FakeImageClient(
        result=ImageResultBundle(
            images=[
                GeneratedImage(url="https://example.com/one.png"),
                GeneratedImage(url="https://example.com/two.png"),
            ],
        ),
        download_results={
            "https://example.com/one.png": (b"one", "image/png", "one.png"),
            "https://example.com/two.png": (b"two", "image/png", "two.png"),
        },
    )
    service = ImageGenerationService(
        client=cast(ImageClient, client),
        detector=cast(ImageDetector, FakeDetector()),
        model_name="model",
        language="en-US",
        incognito=True,
    )

    result = asyncio.run(
        service.generate_if_needed(
            user_message="generate an image set",
            recent_context=[],
            reply_context=None,
        )
    )

    assert result is not None
    assert [asset.filename for asset in result.assets] == ["one.png", "two.png"]
    assert [call["filename_hint"] for call in client.download_calls] == [
        "eva-image-1",
        "eva-image-2",
    ]


def test_image_generation_service_returns_url_bundle_when_downloads_fail() -> None:
    client = FakeImageClient(
        result=ImageResultBundle(
            images=[GeneratedImage(url="https://example.com/fallback.png")],
        ),
        download_results={
            "https://example.com/fallback.png": ImageClientError("cdn failed"),
        },
    )
    service = ImageGenerationService(
        client=cast(ImageClient, client),
        detector=cast(ImageDetector, FakeDetector()),
        model_name="model",
        language="en-US",
        incognito=True,
    )

    result = asyncio.run(
        service.generate_if_needed(
            user_message="generate an image",
            recent_context=[],
            reply_context=None,
        )
    )

    assert result is not None
    assert result.assets == []
    assert result.images[0].url == "https://example.com/fallback.png"
