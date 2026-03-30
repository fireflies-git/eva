from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import discord

from eva.discord.download_commands import handle_download_command
from eva.downloads import DownloadedMediaAsset, DownloadService
from eva.state import WhitelistStore


class DummyTypingContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class FakeDownloadService:
    def __init__(self, *, asset: DownloadedMediaAsset | None = None) -> None:
        self.asset = asset or DownloadedMediaAsset(filename="clip.mp4", data=b"video")
        self.calls: list[dict[str, object]] = []

    async def download_media(self, **kwargs: object) -> DownloadedMediaAsset:
        self.calls.append(kwargs)
        return self.asset


def _make_message(*, author_id: int, guild_filesize_limit: int | None = None) -> discord.Message:
    guild = None
    if guild_filesize_limit is not None:
        guild = SimpleNamespace(filesize_limit=guild_filesize_limit)
    return cast(
        discord.Message,
        SimpleNamespace(
            author=SimpleNamespace(id=author_id),
            guild=guild,
            channel=SimpleNamespace(typing=lambda: DummyTypingContext()),
        ),
    )


def test_download_command_allows_whitelisted_user(tmp_path: Path) -> None:
    whitelist = WhitelistStore(tmp_path / "whitelist.json")
    whitelist.add(200)
    service = FakeDownloadService()

    response = asyncio.run(
        handle_download_command(
            message=_make_message(author_id=200, guild_filesize_limit=8 * 1024 * 1024),
            content="eva dl https://example.com/video",
            is_owner=False,
            trigger_prefix="eva ",
            whitelist=whitelist,
            download_service=cast(DownloadService, service),
        )
    )

    assert response.handled is True
    assert response.content == "✔ Downloaded `clip.mp4`"
    assert response.attachments == [("clip.mp4", b"video")]
    assert service.calls[0]["guild_filesize_limit"] == 8 * 1024 * 1024


def test_download_command_rejects_non_whitelisted_user(tmp_path: Path) -> None:
    whitelist = WhitelistStore(tmp_path / "whitelist.json")

    response = asyncio.run(
        handle_download_command(
            message=_make_message(author_id=999),
            content="eva dl https://example.com/video",
            is_owner=False,
            trigger_prefix="eva ",
            whitelist=whitelist,
            download_service=cast(DownloadService, FakeDownloadService()),
        )
    )

    assert response.handled is True
    assert "don't have permission" in response.content


def test_download_command_returns_usage_when_url_missing(tmp_path: Path) -> None:
    whitelist = WhitelistStore(tmp_path / "whitelist.json")
    whitelist.add(200)

    response = asyncio.run(
        handle_download_command(
            message=_make_message(author_id=200),
            content="eva dl",
            is_owner=False,
            trigger_prefix="eva ",
            whitelist=whitelist,
            download_service=cast(DownloadService, FakeDownloadService()),
        )
    )

    assert response.handled is True
    assert "Usage" in response.content


def test_download_command_supports_download_alias(tmp_path: Path) -> None:
    whitelist = WhitelistStore(tmp_path / "whitelist.json")
    whitelist.add(200)

    response = asyncio.run(
        handle_download_command(
            message=_make_message(author_id=200),
            content="eva download https://example.com/video",
            is_owner=False,
            trigger_prefix="eva ",
            whitelist=whitelist,
            download_service=cast(DownloadService, FakeDownloadService()),
        )
    )

    assert response.handled is True
    assert response.attachments == [("clip.mp4", b"video")]
