import asyncio
from typing import cast

import discord

from eva.ai import ResponseGenerationResult
from eva.ai.orchestrator import ReplyGenerationService
from eva.constants import RESPONSE_WATERMARK
from eva.images import GeneratedImageAsset, ImageResultBundle
from eva.reminders import ReminderConfirmation

_WM = "\n-# -eva"


class StubResponseService:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs: object) -> ResponseGenerationResult:
        self.calls.append(kwargs)
        return ResponseGenerationResult(self.response)


class StubImageService:
    def __init__(self, *, result: ImageResultBundle | None = None) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def generate_if_needed(self, **kwargs: object) -> ImageResultBundle | None:
        self.calls.append(kwargs)
        return self.result


class StubTOSCheckService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def check_tos_violation(self, text: str) -> bool:
        self.calls.append(text)
        return False


class StubReminderScheduler:
    def __init__(self, *, confirmation: ReminderConfirmation | None = None) -> None:
        self.confirmation = confirmation
        self.calls: list[dict[str, object]] = []

    async def schedule_if_needed(self, **kwargs: object) -> ReminderConfirmation | None:
        self.calls.append(kwargs)
        return self.confirmation


class DummyChannel:
    pass


class DummyClient:
    pass


def _build_service(
    *,
    reminder_scheduler: StubReminderScheduler,
    response_service: StubResponseService | None = None,
    image_service: StubImageService | None = None,
) -> ReplyGenerationService:
    return ReplyGenerationService(
        account_mode="assistant",
        response_service=response_service or StubResponseService("normal"),
        image_service=image_service or StubImageService(result=None),
        reminder_scheduler=reminder_scheduler,
        tos_check_service=StubTOSCheckService(),
    )


def test_reminder_confirmation_returned_when_scheduler_hits() -> None:
    scheduler = StubReminderScheduler(
        confirmation=ReminderConfirmation(content="✔ Reminder #1 set for in 5m")
    )
    response_service = StubResponseService("normal")
    image_service = StubImageService(
        result=ImageResultBundle(
            answer="Media generated: 'fox'",
            assets=[GeneratedImageAsset(filename="fox.png", data=b"png-bytes")],
        )
    )
    reply_service = _build_service(
        reminder_scheduler=scheduler,
        response_service=response_service,
        image_service=image_service,
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="remind me in 5m to draw a fox",
            reply_context=None,
            user_id=42,
            channel_id=99,
        )
    )

    assert "Reminder #1" in reply.content
    assert reply.attachments == []
    assert response_service.calls == []
    assert image_service.calls == []
    assert scheduler.calls == [
        {
            "user_message": "remind me in 5m to draw a fox",
            "user_id": 42,
            "channel_id": 99,
        }
    ]


def test_reminder_branch_falls_through_when_scheduler_returns_none() -> None:
    scheduler = StubReminderScheduler(confirmation=None)
    response_service = StubResponseService("normal")
    reply_service = _build_service(
        reminder_scheduler=scheduler,
        response_service=response_service,
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="hey what's up",
            reply_context=None,
            user_id=42,
            channel_id=99,
        )
    )

    assert reply.content == f"normal{_WM}"
    assert len(scheduler.calls) == 1
    assert len(response_service.calls) == 1


def test_reminder_branch_skipped_when_user_id_missing() -> None:
    scheduler = StubReminderScheduler(
        confirmation=ReminderConfirmation(content="✔ Reminder #1 set for in 5m")
    )
    response_service = StubResponseService("normal")
    reply_service = _build_service(
        reminder_scheduler=scheduler,
        response_service=response_service,
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="remind me in 5m",
            reply_context=None,
        )
    )

    assert reply.content == f"normal{_WM}"
    assert scheduler.calls == []
    assert len(response_service.calls) == 1


def test_reminder_branch_skipped_when_no_scheduler_configured() -> None:
    response_service = StubResponseService("normal")
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=response_service,
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="remind me in 5m to do thing",
            reply_context=None,
            user_id=42,
            channel_id=99,
        )
    )

    assert reply.content == f"normal{_WM}"
    assert len(response_service.calls) == 1


def test_reminder_confirmation_is_watermarked() -> None:
    scheduler = StubReminderScheduler(
        confirmation=ReminderConfirmation(content="✔ Reminder #1 set for in 5m")
    )
    reply_service = _build_service(reminder_scheduler=scheduler)

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="remind me in 5m to stretch",
            reply_context=None,
            user_id=42,
            channel_id=99,
        )
    )

    assert reply.content.endswith(RESPONSE_WATERMARK)
    assert reply.content.count(RESPONSE_WATERMARK) == 1


class ViolatingTOSCheckService:
    async def check_tos_violation(self, text: str) -> bool:
        return True


def test_reminder_confirmation_passes_through_tos_check() -> None:
    scheduler = StubReminderScheduler(
        confirmation=ReminderConfirmation(content="✔ Reminder #1 set for in 5m")
    )
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService("normal"),
        image_service=StubImageService(result=None),
        reminder_scheduler=scheduler,
        tos_check_service=ViolatingTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="remind me in 5m to stretch",
            reply_context=None,
            user_id=42,
            channel_id=99,
        )
    )

    assert "violates my safety or TOS guidelines" in reply.content
