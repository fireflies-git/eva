"""Builds the system prompt for the AI."""

from __future__ import annotations

import discord

from eva.prompts.capabilities import build_capabilities_section
from eva.prompts.context import build_context_section
from eva.prompts.environment import build_environment_section
from eva.prompts.formatting import build_formatting_section
from eva.prompts.persona import build_persona_section
from eva.prompts.search import build_search_prompt


def build_system_prompt(
    channel: discord.abc.Messageable,
    client: discord.Client,
    *,
    account_mode: str,
    terminal_enabled: bool,
    autonomous_terminal_enabled: bool,
) -> str:
    sections = [
        build_persona_section(account_mode),
        build_capabilities_section(
            terminal_enabled=terminal_enabled,
            autonomous_terminal_enabled=autonomous_terminal_enabled,
        ),
        build_environment_section(),
        build_formatting_section(),
        build_context_section(channel, client, account_mode),
    ]
    return "\n\n---\n\n".join(sections)


def build_search_system_prompt(
    channel: discord.abc.Messageable,
    client: discord.Client,
    *,
    account_mode: str,
    terminal_enabled: bool,
    autonomous_terminal_enabled: bool,
) -> str:
    sections = [
        build_persona_section(account_mode),
        build_capabilities_section(
            terminal_enabled=terminal_enabled,
            autonomous_terminal_enabled=autonomous_terminal_enabled,
        ),
        build_environment_section(),
        build_formatting_section(),
        build_search_prompt(),
        build_context_section(channel, client, account_mode),
    ]
    return "\n\n---\n\n".join(sections)
