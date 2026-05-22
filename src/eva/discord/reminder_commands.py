"""Reminder commands: schedule, list, forget."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import discord

from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.reminders import (
    ReminderParseError,
    format_duration,
    parse_reminder_command,
)
from eva.state import Reminder, ReminderError, ReminderPersistenceError, ReminderStore

logger = logging.getLogger(__name__)

_REMIND_ALIASES = ("remind", "remindme")
_LIST_ALIASES = ("reminders",)
_FORGET_REMINDER_VERB = "forget"
_FORGET_REMINDER_TARGET = "reminder"


@dataclass(frozen=True, slots=True)
class ReminderCommandResponse:
    handled: bool
    content: str = ""


async def handle_reminder_command(
    *,
    message: discord.Message,
    content: str,
    trigger_prefix: str,
    reminder_store: ReminderStore,
) -> ReminderCommandResponse:
    parsed = _parse_command(content=content, trigger_prefix=trigger_prefix)
    if parsed is None:
        return ReminderCommandResponse(handled=False)

    verb, argument = parsed
    user_id = message.author.id
    channel_id = getattr(message.channel, "id", None)

    if verb in _LIST_ALIASES:
        return _list_reminders(reminder_store, user_id=user_id)
    if verb == _FORGET_REMINDER_VERB:
        return _forget_reminder(reminder_store, user_id=user_id, argument=argument)
    if verb in _REMIND_ALIASES:
        if channel_id is None:
            return ReminderCommandResponse(
                handled=True,
                content=f"{X_MARK} I can't set a reminder here.",
            )
        return _schedule_reminder(
            reminder_store,
            user_id=user_id,
            channel_id=channel_id,
            argument=argument,
        )

    return ReminderCommandResponse(handled=False)


def _schedule_reminder(
    reminder_store: ReminderStore,
    *,
    user_id: int,
    channel_id: int,
    argument: str,
) -> ReminderCommandResponse:
    try:
        parsed = parse_reminder_command(argument)
    except ReminderParseError as exc:
        return ReminderCommandResponse(handled=True, content=f"{WARNING_MARK} {exc}")

    fire_at = datetime.now(timezone.utc) + parsed.duration
    try:
        reminder = reminder_store.add(
            user_id=user_id,
            channel_id=channel_id,
            fire_at=fire_at,
            text=parsed.text,
        )
    except ReminderError as exc:
        return ReminderCommandResponse(handled=True, content=f"{WARNING_MARK} {exc}")
    except ReminderPersistenceError:
        return ReminderCommandResponse(
            handled=True,
            content=f"{X_MARK} Failed to persist your reminder. Try again later.",
        )

    pretty_duration = format_duration(parsed.duration)
    return ReminderCommandResponse(
        handled=True,
        content=(
            f"{CHECK_MARK} Reminder #{reminder.id} set for in {pretty_duration} — "
            f"\"{reminder.text}\""
        ),
    )


def _list_reminders(
    reminder_store: ReminderStore,
    *,
    user_id: int,
) -> ReminderCommandResponse:
    reminders = reminder_store.list_for_user(user_id)
    if not reminders:
        return ReminderCommandResponse(
            handled=True,
            content=f"{WARNING_MARK} You have no active reminders.",
        )
    now = datetime.now(timezone.utc)
    lines = [f"{CHECK_MARK} Your reminders:"]
    for reminder in reminders:
        remaining = reminder.fire_at - now
        when = (
            "due now"
            if remaining.total_seconds() <= 0
            else f"in {format_duration(remaining)}"
        )
        lines.append(f"#{reminder.id} ({when}): {reminder.text}")
    return ReminderCommandResponse(handled=True, content="\n".join(lines))


def _forget_reminder(
    reminder_store: ReminderStore,
    *,
    user_id: int,
    argument: str,
) -> ReminderCommandResponse:
    normalized = argument.strip().lower()
    if not normalized.startswith(_FORGET_REMINDER_TARGET):
        return ReminderCommandResponse(handled=False)

    after_target = normalized[len(_FORGET_REMINDER_TARGET) :].strip()
    if not after_target:
        return ReminderCommandResponse(
            handled=True,
            content=f"{WARNING_MARK} Usage: `forget reminder <id>`.",
        )

    try:
        reminder_id = int(after_target)
    except ValueError:
        return ReminderCommandResponse(
            handled=True,
            content=f"{WARNING_MARK} Usage: `forget reminder <id>`.",
        )

    try:
        removed = reminder_store.remove(user_id=user_id, reminder_id=reminder_id)
    except ReminderPersistenceError:
        return ReminderCommandResponse(
            handled=True,
            content=f"{X_MARK} Failed to persist your reminder change. Try again later.",
        )
    if removed is None:
        return ReminderCommandResponse(
            handled=True,
            content=f"{WARNING_MARK} No reminder #{reminder_id} of yours.",
        )
    return _format_removed(removed)


def _format_removed(reminder: Reminder) -> ReminderCommandResponse:
    return ReminderCommandResponse(
        handled=True,
        content=f"{CHECK_MARK} Forgot reminder #{reminder.id}: \"{reminder.text}\"",
    )


def _parse_command(*, content: str, trigger_prefix: str) -> tuple[str, str] | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None
    remainder = text[len(prefix) :].lstrip()
    lowered = remainder.lower()

    for verb in (*_REMIND_ALIASES, *_LIST_ALIASES):
        if lowered == verb:
            return verb, ""
        if lowered.startswith(f"{verb} "):
            return verb, remainder[len(verb) :].strip()

    # `forget reminder <id>` (the bare `forget` verb is owned by memory commands;
    # we only intercept when the second token is `reminder`).
    if lowered.startswith(f"{_FORGET_REMINDER_VERB} "):
        rest = remainder[len(_FORGET_REMINDER_VERB) :].strip()
        if rest.lower().startswith(_FORGET_REMINDER_TARGET):
            return _FORGET_REMINDER_VERB, rest
    return None
