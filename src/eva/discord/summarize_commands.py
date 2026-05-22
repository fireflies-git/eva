"""Channel summarization command."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import discord

from eva.ai import AIClientError, SummarizationEmptyError, SummarizationService
from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.discord.context import fetch_channel_context

logger = logging.getLogger(__name__)

_SUMMARIZE_ALIASES = ("summarize", "tldr")
DEFAULT_SUMMARIZE_MESSAGES = 50
SUMMARIZE_MESSAGES_MIN = 5
SUMMARIZE_MESSAGES_MAX = 200


def is_summarize_command(*, content: str, trigger_prefix: str) -> bool:
    """Cheap prefix check used by the handler to gate AI rate limiting."""
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return False
    remainder = text[len(prefix) :].lstrip().lower()
    for verb in _SUMMARIZE_ALIASES:
        if remainder == verb or remainder.startswith(f"{verb} "):
            return True
    return False


@dataclass(frozen=True, slots=True)
class SummarizeCommandResponse:
    handled: bool
    content: str = ""


@dataclass(frozen=True, slots=True)
class _ParsedSummarize:
    requested_count: int | None
    argument_invalid: bool


async def handle_summarize_command(
    *,
    message: discord.Message,
    content: str,
    trigger_prefix: str,
    summarization_service: SummarizationService | None,
    requester_context: str | None = None,
) -> SummarizeCommandResponse:
    parsed = _parse_summarize_command(content=content, trigger_prefix=trigger_prefix)
    if parsed is None:
        return SummarizeCommandResponse(handled=False)

    if summarization_service is None:
        return SummarizeCommandResponse(
            handled=True,
            content=f"{X_MARK} Summarization is not available right now.",
        )

    if parsed.argument_invalid:
        return SummarizeCommandResponse(
            handled=True,
            content=(
                f"{WARNING_MARK} Usage: `summarize [N]` where N is between "
                f"{SUMMARIZE_MESSAGES_MIN} and {SUMMARIZE_MESSAGES_MAX}."
            ),
        )

    requested = parsed.requested_count
    if requested is None:
        limit = DEFAULT_SUMMARIZE_MESSAGES
    elif requested < SUMMARIZE_MESSAGES_MIN or requested > SUMMARIZE_MESSAGES_MAX:
        return SummarizeCommandResponse(
            handled=True,
            content=(
                f"{WARNING_MARK} Choose a number between "
                f"{SUMMARIZE_MESSAGES_MIN} and {SUMMARIZE_MESSAGES_MAX}."
            ),
        )
    else:
        limit = requested

    channel_messages = await fetch_channel_context(
        message.channel,
        limit=limit,
        exclude_message_id=message.id,
    )
    if not channel_messages:
        return SummarizeCommandResponse(
            handled=True,
            content=f"{WARNING_MARK} I couldn't find any recent messages to summarize.",
        )

    try:
        summary = await summarization_service.summarize(
            channel_messages=channel_messages,
            requester_context=requester_context,
        )
    except SummarizationEmptyError as exc:
        return SummarizeCommandResponse(handled=True, content=f"{WARNING_MARK} {exc}")
    except AIClientError as exc:
        logger.exception("Summarization failed")
        return SummarizeCommandResponse(
            handled=True,
            content=f"{X_MARK} Couldn't summarize: {exc}",
        )

    summary = summary.strip()
    if not summary:
        return SummarizeCommandResponse(
            handled=True,
            content=f"{WARNING_MARK} Got an empty summary back.",
        )

    header = f"{CHECK_MARK} Summary of the last {len(channel_messages)} messages:"
    return SummarizeCommandResponse(handled=True, content=f"{header}\n{summary}")


def _parse_summarize_command(
    *,
    content: str,
    trigger_prefix: str,
) -> _ParsedSummarize | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None
    remainder = text[len(prefix) :].lstrip()
    lowered = remainder.lower()

    for verb in _SUMMARIZE_ALIASES:
        if lowered == verb:
            return _ParsedSummarize(requested_count=None, argument_invalid=False)
        if lowered.startswith(f"{verb} "):
            argument = remainder[len(verb) :].strip()
            if not argument:
                return _ParsedSummarize(requested_count=None, argument_invalid=False)
            try:
                return _ParsedSummarize(requested_count=int(argument), argument_invalid=False)
            except ValueError:
                return _ParsedSummarize(requested_count=None, argument_invalid=True)
    return None
