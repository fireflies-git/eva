import asyncio

import pytest

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


class _FakeStream:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def iter_chunked(self, chunk_size: int):
        async def _gen():
            for chunk in self._chunks:
                yield chunk

        return _gen()


class _FakeResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status = status
        self.headers = headers or {}
        self.content = _FakeStream(chunks or [])
        self.body_read = False

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def text(self) -> str:
        self.body_read = True
        return "error body"


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def get(self, url: str) -> _FakeResponse:
        return self._response


def _download_client(response: _FakeResponse) -> ImageClient:
    client = ImageClient(
        api_key="test", base_url="https://example.com/v1", timeout_seconds=30.0
    )
    # download_asset only needs .get(); wrap the response accordingly.
    client._session = _FakeSession(response)  # type: ignore[assignment]
    return client


def test_download_asset_rejects_oversized_content_length_early() -> None:
    response = _FakeResponse(
        headers={"Content-Length": str(10_000), "Content-Type": "image/png"},
        chunks=[b"x" * 10_000],
    )
    client = _download_client(response)

    with pytest.raises(ImageClientError, match="exceeds max size"):
        asyncio.run(
            client.download_asset(url="https://example.com/big.png", max_bytes=100)
        )


def test_download_asset_aborts_stream_when_body_exceeds_cap() -> None:
    response = _FakeResponse(
        headers={"Content-Type": "image/png"},
        chunks=[b"x" * 60, b"y" * 60],
    )
    client = _download_client(response)

    with pytest.raises(ImageClientError, match="exceeds max size"):
        asyncio.run(
            client.download_asset(url="https://example.com/stream.png", max_bytes=100)
        )


def test_download_asset_returns_body_within_cap() -> None:
    response = _FakeResponse(
        headers={"Content-Type": "image/png"},
        chunks=[b"png-", b"bytes"],
    )
    client = _download_client(response)

    raw, content_type, filename = asyncio.run(
        client.download_asset(url="https://example.com/ok.png", max_bytes=100)
    )

    assert raw == b"png-bytes"
    assert content_type == "image/png"
    assert filename.endswith(".png")


def test_download_asset_ignores_garbage_content_length() -> None:
    response = _FakeResponse(
        headers={"Content-Length": "not-a-number", "Content-Type": "image/png"},
        chunks=[b"ok"],
    )
    client = _download_client(response)

    raw, _, _ = asyncio.run(
        client.download_asset(url="https://example.com/ok.png", max_bytes=100)
    )

    assert raw == b"ok"
