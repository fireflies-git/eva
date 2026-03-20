import asyncio

from eva.images.client import ImageClient


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
            "answer": "Media generated",
            "images": [
                {
                    "url": "https://example.com/image.png",
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
    assert result.answer == "Media generated"
    assert len(result.images) == 1
    assert result.images[0].url == "https://example.com/image.png"
    assert result.images[0].thumbnail_url == "https://example.com/thumb.png"


def test_image_client_ignores_invalid_images() -> None:
    client = StubImageClient(
        {
            "images": [
                {"thumbnail_url": "missing url"},
                {"url": "https://example.com/ok.png"},
                "not-a-dict",
            ]
        }
    )

    result = asyncio.run(
        client.generate(prompt="p", model="sonar", language="en-US", incognito=True)
    )

    assert len(result.images) == 1
    assert result.images[0].url == "https://example.com/ok.png"
