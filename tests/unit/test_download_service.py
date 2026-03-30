from __future__ import annotations

import asyncio
from pathlib import Path
from typing import cast

import pytest

from eva.constants import DEFAULT_DM_DOWNLOAD_LIMIT_BYTES
from eva.downloads import DownloadClientError, DownloadedMediaFile, DownloadService
from eva.downloads.client import MediaDownloader


class FakeDownloadClient:
    def __init__(
        self,
        *,
        filename: str = "clip.mp4",
        payload: bytes = b"video",
        return_missing_file: bool = False,
    ) -> None:
        self.filename = filename
        self.payload = payload
        self.return_missing_file = return_missing_file
        self.calls: list[dict[str, object]] = []

    async def download(
        self,
        *,
        url: str,
        max_filesize_mb: float,
        temp_dir: Path,
    ) -> DownloadedMediaFile:
        self.calls.append(
            {
                "url": url,
                "max_filesize_mb": max_filesize_mb,
                "temp_dir": temp_dir,
            }
        )
        path = temp_dir / self.filename
        if not self.return_missing_file:
            path.write_bytes(self.payload)
        return DownloadedMediaFile(path=path)


def test_download_service_downloads_media_with_guild_limit() -> None:
    client = FakeDownloadClient()
    service = DownloadService(client=cast(MediaDownloader, client))

    result = asyncio.run(
        service.download_media(
            url="https://example.com/video",
            guild_filesize_limit=8 * 1024 * 1024,
        )
    )

    assert result.filename == "clip.mp4"
    assert result.data == b"video"
    assert client.calls[0]["max_filesize_mb"] == 8.0


def test_download_service_uses_dm_limit_when_guild_limit_missing() -> None:
    client = FakeDownloadClient()
    service = DownloadService(client=cast(MediaDownloader, client))

    asyncio.run(
        service.download_media(
            url="https://example.com/video",
            guild_filesize_limit=None,
        )
    )

    assert client.calls[0]["max_filesize_mb"] == DEFAULT_DM_DOWNLOAD_LIMIT_BYTES / (1024 * 1024)


def test_download_service_rejects_invalid_url() -> None:
    service = DownloadService(client=cast(MediaDownloader, FakeDownloadClient()))

    with pytest.raises(DownloadClientError, match="valid URL"):
        asyncio.run(service.download_media(url="not-a-url", guild_filesize_limit=None))


def test_download_service_rejects_missing_downloaded_file() -> None:
    service = DownloadService(
        client=cast(MediaDownloader, FakeDownloadClient(return_missing_file=True))
    )

    with pytest.raises(DownloadClientError, match="Failed to download the video"):
        asyncio.run(
            service.download_media(
                url="https://example.com/video",
                guild_filesize_limit=8 * 1024 * 1024,
            )
        )


def test_download_service_rejects_oversized_file() -> None:
    service = DownloadService(
        client=cast(MediaDownloader, FakeDownloadClient(payload=b"x" * (2 * 1024 * 1024)))
    )

    with pytest.raises(DownloadClientError, match="too large to upload"):
        asyncio.run(
            service.download_media(
                url="https://example.com/video",
                guild_filesize_limit=1 * 1024 * 1024,
            )
        )
