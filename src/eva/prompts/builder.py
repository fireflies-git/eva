"""Builds the system prompt for the AI."""

from __future__ import annotations

from collections.abc import Collection

import discord

from eva.prompts.capabilities import build_capabilities_section
from eva.prompts.context import build_context_section
from eva.prompts.custom_persona import build_custom_persona_section
from eva.prompts.environment import build_environment_section
from eva.prompts.formatting import build_formatting_section
from eva.prompts.friend_request import FRIEND_REQUEST_REVIEW_INSTRUCTIONS
from eva.prompts.persona import build_persona_section
from eva.prompts.security import build_security_section
from eva.state.personas import Persona


def build_friend_request_review_prompt(*, account_mode: str) -> str:
    """Compose Eva's persona with the friend-request review instructions."""
    return "\n\n---\n\n".join(
        [build_persona_section(), FRIEND_REQUEST_REVIEW_INSTRUCTIONS]
    )


def build_system_prompt(
    channel: discord.abc.Messageable,
    client: discord.Client,
    *,
    account_mode: str,
    available_tools: Collection[str] = frozenset(),
    requester_is_admin: bool = False,
    custom_persona: Persona | None = None,
) -> str:
    sections = [
        build_persona_section(requester_is_admin=requester_is_admin),
        build_custom_persona_section(custom_persona),
        build_capabilities_section(available_tools=available_tools),
        build_environment_section(),
        build_formatting_section(allow_message_splitting=account_mode == "standalone"),
        build_context_section(channel, client),
        build_security_section(),
    ]
    return "\n\n---\n\n".join(section for section in sections if section)
