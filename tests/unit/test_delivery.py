from __future__ import annotations

import asyncio
from typing import cast

import discord

from eva.discord.delivery import deliver_owner_response, deliver_reply_response


class FakeSentMessage:
    def __init__(self, message_id: int) -> None:
        self.id = message_id


class FakeChannel:
    def __init__(
        self,
        *,
        send_ids: list[int] | None = None,
        fail_send_calls: set[int] | None = None,
    ) -> None:
        self._send_ids = list(send_ids or [])
        self._fail_send_calls = fail_send_calls or set()
        self._send_calls = 0
        self._next_generated_id = 1000

    async def send(self, *, content: str, suppress_embeds: bool) -> FakeSentMessage:
        self._send_calls += 1
        if self._send_calls in self._fail_send_calls:
            raise RuntimeError("send failed")
        if self._send_ids:
            return FakeSentMessage(self._send_ids.pop(0))
        message_id = self._next_generated_id
        self._next_generated_id += 1
        return FakeSentMessage(message_id)


class FakeOwnerMessage:
    def __init__(self, *, message_id: int, channel: FakeChannel, fail_edit: bool = False) -> None:
        self.id = message_id
        self.channel = channel
        self._fail_edit = fail_edit

    async def edit(self, *, content: str, suppress: bool) -> None:
        if self._fail_edit:
            raise RuntimeError("edit failed")


class FakeReplyMessage:
    def __init__(
        self,
        *,
        channel: FakeChannel,
        first_reply_id: int = 0,
        fail_reply: bool = False,
    ) -> None:
        self.channel = channel
        self._first_reply_id = first_reply_id
        self._fail_reply = fail_reply

    async def reply(self, *, content: str, suppress_embeds: bool) -> FakeSentMessage:
        if self._fail_reply:
            raise RuntimeError("reply failed")
        return FakeSentMessage(self._first_reply_id)


def test_deliver_owner_response_tracks_primary_and_continuations() -> None:
    channel = FakeChannel(send_ids=[11, 12])
    message = FakeOwnerMessage(message_id=10, channel=channel)

    result = asyncio.run(
        deliver_owner_response(
            message=cast(discord.Message, message),
            original_content="eva summarize",
            reply_content="x" * 6000,
        )
    )

    assert result.primary_delivered is True
    assert result.tracked_message_ids[:3] == [10, 11, 12]
    assert result.had_continuation_failures is False


def test_deliver_owner_response_does_not_track_if_primary_edit_fails() -> None:
    channel = FakeChannel(send_ids=[11])
    message = FakeOwnerMessage(message_id=10, channel=channel, fail_edit=True)

    result = asyncio.run(
        deliver_owner_response(
            message=cast(discord.Message, message),
            original_content="eva summarize",
            reply_content="response",
        )
    )

    assert result.primary_delivered is False
    assert result.tracked_message_ids == []


def test_deliver_reply_response_tracks_primary_and_continuations() -> None:
    channel = FakeChannel(send_ids=[21, 22])
    message = FakeReplyMessage(channel=channel, first_reply_id=20)

    result = asyncio.run(
        deliver_reply_response(
            message=cast(discord.Message, message),
            reply_content="x" * 6000,
        )
    )

    assert result.primary_delivered is True
    assert result.tracked_message_ids == [20, 21, 22]
    assert result.had_continuation_failures is False


def test_deliver_reply_response_does_not_track_if_reply_fails() -> None:
    channel = FakeChannel(send_ids=[21])
    message = FakeReplyMessage(channel=channel, first_reply_id=20, fail_reply=True)

    result = asyncio.run(
        deliver_reply_response(
            message=cast(discord.Message, message),
            reply_content="response",
        )
    )

    assert result.primary_delivered is False
    assert result.tracked_message_ids == []


def test_deliver_owner_response_marks_continuation_failures_without_tracking_unsent_ids() -> None:
    channel = FakeChannel(send_ids=[11], fail_send_calls={2, 3, 4, 5})
    message = FakeOwnerMessage(message_id=10, channel=channel)

    result = asyncio.run(
        deliver_owner_response(
            message=cast(discord.Message, message),
            original_content="eva summarize",
            reply_content="x" * 6000,
        )
    )

    assert result.primary_delivered is True
    assert 10 in result.tracked_message_ids
    assert 11 in result.tracked_message_ids
    assert result.tracked_message_ids == [10, 11]
    assert result.had_continuation_failures is True
