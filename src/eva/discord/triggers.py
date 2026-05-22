from __future__ import annotations

from dataclasses import dataclass

import discord

from eva.state import TrackedMessageStore


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    should_process: bool
    user_query: str = ""
    is_reply_trigger: bool = False


def decide_standalone_trigger(
    *,
    message: discord.Message,
    content: str,
    trigger_prefix: str,
    is_reply_trigger: bool,
    mention_user_id: int,
) -> TriggerDecision:
    text = content.strip()
    if not text:
        return TriggerDecision(should_process=False)

    if _is_dm_channel(message.channel):
        return TriggerDecision(should_process=True, user_query=text)

    if is_reply_trigger:
        return TriggerDecision(
            should_process=True,
            user_query=text,
            is_reply_trigger=True,
        )

    prefixed = parse_trigger(
        content=content,
        trigger_prefix=trigger_prefix,
        is_reply_trigger=False,
        mention_user_id=None,
    )
    if prefixed.should_process:
        return prefixed

    if _message_mentions_user(message, mention_user_id):
        query = _strip_user_mentions(content, mention_user_id).strip()
        if query:
            return TriggerDecision(should_process=True, user_query=query)

    return TriggerDecision(should_process=False)


def _is_dm_channel(channel: discord.abc.Messageable) -> bool:
    return getattr(channel, "guild", None) is None


def _message_mentions_user(message: discord.Message, user_id: int) -> bool:
    raw_mentions = getattr(message, "raw_mentions", None)
    if isinstance(raw_mentions, list) and user_id in raw_mentions:
        return True
    content = getattr(message, "content", "")
    return f"<@{user_id}>" in content or f"<@!{user_id}>" in content


def _strip_user_mentions(content: str, user_id: int) -> str:
    stripped = content.replace(f"<@{user_id}>", " ")
    stripped = stripped.replace(f"<@!{user_id}>", " ")
    return " ".join(stripped.split())


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
