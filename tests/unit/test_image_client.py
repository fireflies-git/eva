import asyncio

from eva.images.client import ImageClient, ImageClientError


class StubImageClient(ImageClient):
    def __init__(self, payload: dict[str, object]) -> None:
        super().__init__(api_key="test", base_url="https://example.com/v1", timeout_seconds=30.0)
        self._payload = payload

    async def _request(self, **kwargs: object) -> dict[str, object]:
        return self._payload


def test_image_client_normalizes_payload() -> None:
    client = StubImageClient(
        {
            "id": "req_123",
            "model": "sonar",
            "prompt": "Generate an image",
            "image_generation": True,
            "answer": "Media generated",
            "images": [
                {
                    "url": "https://user-gen-media-assets.s3.amazonaws.com/seedream_images/example.png",
                    "thumbnail_url": "https://example.com/thumb.png",
                    "download_url": "https://example.com/download.png",
                    "mime_type": "image/png",
                    "source": "seedream-router",
                    "generation_model": "seedream",
                    "prompt": "red fox",
                }
            ],
        }
    )

    result = asyncio.run(
        client.generate(prompt="p", model="sonar", language="en-US", incognito=True)
    )

    assert result.id == "req_123"
    assert result.model == "sonar"
    assert result.image_generation is True
    assert result.answer == "Media generated"
    assert len(result.images) == 1
    assert result.images[0].url == "https://user-gen-media-assets.s3.amazonaws.com/seedream_images/example.png"
    assert result.images[0].thumbnail_url == "https://example.com/thumb.png"


def test_image_client_ignores_invalid_images() -> None:
    client = StubImageClient(
        {
            "images": [
                {"thumbnail_url": "missing url"},
                {
                    "url": "https://user-gen-media-assets.s3.amazonaws.com/seedream_images/ok.png",
                    "source": "seedream-router",
                },
                "not-a-dict",
            ]
        }
    )

    result = asyncio.run(
        client.generate(prompt="p", model="sonar", language="en-US", incognito=True)
    )

    assert len(result.images) == 1
    assert result.images[0].url == (
        "https://user-gen-media-assets.s3.amazonaws.com/seedream_images/ok.png"
    )


def test_image_client_rejects_non_generated_image_results() -> None:
    client = StubImageClient(
        {
            "image_generation": True,
            "images": [
                {
                    "url": "https://example.com/web-result.png",
                    "source": "web",
                }
            ],
        }
    )

    try:
        asyncio.run(client.generate(prompt="p", model="sonar", language="en-US", incognito=True))
    except ImageClientError as exc:
        assert str(exc) == "Image API returned non-generated image results"
    else:
        raise AssertionError("expected ImageClientError for non-generated image results")
