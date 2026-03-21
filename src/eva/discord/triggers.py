from __future__ import annotations

from dataclasses import dataclass

import discord

from eva.state import TrackedMessageStore


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    should_process: bool
    user_query: str = ""
    is_reply_trigger: bool = False


def parse_trigger(
    *,
    content: str,
    trigger_prefix: str,
    is_reply_trigger: bool,
    mention_user_id: int | None = None,
) -> TriggerDecision:
    text = content.strip()
    lowered = text.lower()

    if is_reply_trigger:
        if not text:
            return TriggerDecision(should_process=False)
        return TriggerDecision(
            should_process=True,
            user_query=text,
            is_reply_trigger=True,
        )

    prefix = trigger_prefix.lower()
    if lowered.startswith(prefix):
        query = text[len(trigger_prefix) :].strip()
        if not query:
            return TriggerDecision(should_process=False)
        return TriggerDecision(
            should_process=True,
            user_query=query,
            is_reply_trigger=False,
        )

    if mention_user_id is None:
        return TriggerDecision(should_process=False)

    mention_prefixes = (f"<@{mention_user_id}>", f"<@!{mention_user_id}>")
    for mention_prefix in mention_prefixes:
        if text.startswith(mention_prefix):
            query = text[len(mention_prefix) :].strip()
            if not query:
                return TriggerDecision(should_process=False)
            return TriggerDecision(
                should_process=True,
                user_query=query,
                is_reply_trigger=False,
            )

    return TriggerDecision(should_process=False)


def is_tracked_reply_trigger(
    *,
    message: discord.Message,
    tracked_messages: TrackedMessageStore,
) -> bool:
    if not (message.reference and message.reference.message_id):
        return False
    return tracked_messages.contains(message.reference.message_id)
