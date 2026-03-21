from types import SimpleNamespace
from typing import cast

import discord

from eva.discord.handlers import is_tracked_reply_trigger, parse_trigger
from eva.state import TrackedMessageStore


def test_parse_trigger_with_prefix_message() -> None:
    result = parse_trigger(
        content="eva tell me a joke",
        trigger_prefix="eva ",
        is_reply_trigger=False,
        mention_user_id=123,
    )
    assert result.should_process is True
    assert result.user_query == "tell me a joke"
    assert result.is_reply_trigger is False


def test_parse_trigger_reply_retrigger() -> None:
    result = parse_trigger(
        content="continue that",
        trigger_prefix="eva ",
        is_reply_trigger=True,
        mention_user_id=123,
    )
    assert result.should_process is True
    assert result.user_query == "continue that"
    assert result.is_reply_trigger is True


def test_parse_trigger_non_match() -> None:
    result = parse_trigger(
        content="random message",
        trigger_prefix="eva ",
        is_reply_trigger=False,
        mention_user_id=123,
    )
    assert result.should_process is False


def test_parse_trigger_empty_query_after_prefix() -> None:
    result = parse_trigger(
        content="eva ",
        trigger_prefix="eva ",
        is_reply_trigger=False,
        mention_user_id=123,
    )
    assert result.should_process is False


def test_parse_trigger_with_user_mention() -> None:
    result = parse_trigger(
        content="<@123> tell me a joke",
        trigger_prefix="eva ",
        is_reply_trigger=False,
        mention_user_id=123,
    )
    assert result.should_process is True
    assert result.user_query == "tell me a joke"
    assert result.is_reply_trigger is False


def test_parse_trigger_empty_query_after_mention() -> None:
    result = parse_trigger(
        content="<@123>",
        trigger_prefix="eva ",
        is_reply_trigger=False,
        mention_user_id=123,
    )
    assert result.should_process is False


def test_is_tracked_reply_trigger_returns_true_for_tracked_reply() -> None:
    tracked_messages = TrackedMessageStore()
    tracked_messages.add(123)

    message = SimpleNamespace(reference=SimpleNamespace(message_id=123))

    assert (
        is_tracked_reply_trigger(
            message=cast(discord.Message, message),
            tracked_messages=tracked_messages,
        )
        is True
    )


def test_is_tracked_reply_trigger_returns_false_for_untracked_reply() -> None:
    tracked_messages = TrackedMessageStore()
    tracked_messages.add(123)

    message = SimpleNamespace(reference=SimpleNamespace(message_id=456))

    assert (
        is_tracked_reply_trigger(
            message=cast(discord.Message, message),
            tracked_messages=tracked_messages,
        )
        is False
    )
