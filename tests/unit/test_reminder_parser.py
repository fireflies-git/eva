from datetime import timedelta

import pytest

from eva.reminders.parser import (
    ReminderParseError,
    format_duration,
    parse_duration,
    parse_reminder_command,
)


def test_parse_duration_simple_units() -> None:
    assert parse_duration("2h") == timedelta(hours=2)
    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("45s") == timedelta(seconds=45)
    assert parse_duration("1d") == timedelta(days=1)
    assert parse_duration("1w") == timedelta(weeks=1)


def test_parse_duration_compound() -> None:
    assert parse_duration("1d2h30m") == timedelta(days=1, hours=2, minutes=30)
    assert parse_duration("2h 15m") == timedelta(hours=2, minutes=15)


def test_parse_duration_rejects_garbage() -> None:
    assert parse_duration("") is None
    assert parse_duration("hello") is None
    assert parse_duration("2h banana") is None
    assert parse_duration("0s") is None


def test_parse_duration_word_units() -> None:
    assert parse_duration("45 min") == timedelta(minutes=45)
    assert parse_duration("45min") == timedelta(minutes=45)
    assert parse_duration("2 hours") == timedelta(hours=2)
    assert parse_duration("1 hour") == timedelta(hours=1)
    assert parse_duration("3 days") == timedelta(days=3)
    assert parse_duration("1 week") == timedelta(weeks=1)
    assert parse_duration("90 secs") == timedelta(seconds=90)
    assert parse_duration("1 hr 30 min") == timedelta(hours=1, minutes=30)


def test_parse_duration_rejects_unit_lookalikes() -> None:
    assert parse_duration("3 milk") is None
    assert parse_duration("2 months") is None
    assert parse_duration("5 man") is None


def test_parse_reminder_command_word_duration() -> None:
    result = parse_reminder_command("me in 45 min call mom")
    assert result.duration == timedelta(minutes=45)
    assert result.text == "call mom"


def test_parse_reminder_command_multi_token_word_duration() -> None:
    result = parse_reminder_command("me in 1 hour 30 minutes stretch")
    assert result.duration == timedelta(hours=1, minutes=30)
    assert result.text == "stretch"


def test_format_duration_round_trip() -> None:
    assert format_duration(timedelta(seconds=90)) == "1m30s"
    assert format_duration(timedelta(hours=2, minutes=5)) == "2h5m"
    assert format_duration(timedelta(0)) == "0s"


def test_parse_reminder_command_full_form() -> None:
    result = parse_reminder_command("me in 2h to call mom")
    assert result.duration == timedelta(hours=2)
    assert result.text == "call mom"


def test_parse_reminder_command_no_me_no_in() -> None:
    result = parse_reminder_command("2h drink water")
    assert result.duration == timedelta(hours=2)
    assert result.text == "drink water"


def test_parse_reminder_command_compound_duration() -> None:
    result = parse_reminder_command("me in 1h 30m grab keys")
    assert result.duration == timedelta(hours=1, minutes=30)
    assert result.text == "grab keys"


def test_parse_reminder_command_that_keyword() -> None:
    result = parse_reminder_command("me in 10m that meeting starts")
    assert result.text == "meeting starts"


def test_parse_reminder_command_missing_duration() -> None:
    with pytest.raises(ReminderParseError):
        parse_reminder_command("me to do something")


def test_parse_reminder_command_missing_text() -> None:
    with pytest.raises(ReminderParseError):
        parse_reminder_command("me in 2h")


def test_parse_reminder_command_empty() -> None:
    with pytest.raises(ReminderParseError):
        parse_reminder_command("")
