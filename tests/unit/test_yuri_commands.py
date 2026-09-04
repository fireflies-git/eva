from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import discord

from eva.discord.yuri_commands import handle_yuri_command
from eva.yuri import YuriDatabaseError, YuriImageAsset


class DummyTypingContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None


class FakeYuriService:
    def __init__(
        self,
        result: YuriImageAsset | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.max_bytes: int | None = None
        self.allow_nsfw: bool | None = None

    async def get_random_image(
        self,
        *,
        max_bytes: int,
        allow_nsfw: bool,
    ) -> YuriImageAsset:
        self.max_bytes = max_bytes
        self.allow_nsfw = allow_nsfw
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _make_message() -> discord.Message:
    return cast(
        discord.Message,
        SimpleNamespace(
            channel=SimpleNamespace(typing=lambda: DummyTypingContext()),
        ),
    )


def test_yuri_command_returns_image_attachment_and_warning_for_nsfw() -> None:
    service = FakeYuriService(
        result=YuriImageAsset(
            image_id=42,
            filename="yuri-42.jpg",
            data=b"jpeg",
            permalink="/post/42",
            is_nsfw=True,
        )
    )

    outcome = asyncio.run(
        handle_yuri_command(
            message=_make_message(),
            content="eva yuri",
            trigger_prefix="eva ",
            yuri_service=service,
            allow_nsfw=True,
        )
    )

    assert outcome.handled is True
    assert "Marked NSFW" in outcome.content
    assert outcome.attachments == [("yuri-42.jpg", b"jpeg")]
    assert outcome.spoiler_attachments is True
    assert service.max_bytes == 128 * 1024 * 1024
    assert service.allow_nsfw is True


def test_yuri_command_ignores_non_command_text() -> None:
    outcome = asyncio.run(
        handle_yuri_command(
            message=_make_message(),
            content="eva yuri please",
            trigger_prefix="eva ",
            yuri_service=None,
            allow_nsfw=False,
        )
    )

    assert outcome.handled is False


def test_yuri_command_reports_missing_service() -> None:
    outcome = asyncio.run(
        handle_yuri_command(
            message=_make_message(),
            content="eva yuri",
            trigger_prefix="eva ",
            yuri_service=None,
            allow_nsfw=False,
        )
    )

    assert outcome.handled is True
    assert "disabled" in outcome.content


def test_yuri_command_reports_database_failure() -> None:
    service = FakeYuriService(error=YuriDatabaseError("database is broken"))

    outcome = asyncio.run(
        handle_yuri_command(
            message=_make_message(),
            content="eva yuri",
            trigger_prefix="eva ",
            yuri_service=service,
            allow_nsfw=False,
        )
    )

    assert outcome.handled is True
    assert outcome.attachments is None
    assert "database is broken" in outcome.content


def test_yuri_command_requests_sfw_images_for_untrusted_requesters() -> None:
    service = FakeYuriService(
        result=YuriImageAsset(
            image_id=9,
            filename="yuri-9.png",
            data=b"png",
            permalink=None,
            is_nsfw=False,
        )
    )

    outcome = asyncio.run(
        handle_yuri_command(
            message=_make_message(),
            content="eva yuri",
            trigger_prefix="eva ",
            yuri_service=service,
            allow_nsfw=False,
        )
    )

    assert outcome.attachments == [("yuri-9.png", b"png")]
    assert outcome.spoiler_attachments is False
    assert service.allow_nsfw is False
