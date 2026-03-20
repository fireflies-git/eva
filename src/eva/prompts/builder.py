"""Builds the system prompt for the AI."""

from __future__ import annotations

import discord

from eva.prompts.capabilities import build_capabilities_section
from eva.prompts.context import build_context_section
from eva.prompts.formatting import build_formatting_section
from eva.prompts.persona import build_persona_section
from eva.prompts.search import build_search_prompt
from eva.prompts.security import build_security_section


def build_system_prompt(channel: discord.abc.Messageable, client: discord.Client) -> str:
    sections = [
        build_security_section(),
        build_persona_section(),
        build_formatting_section(),
        build_capabilities_section(),
        build_context_section(channel, client),
    ]
    return "\n\n---\n\n".join(sections)


def build_search_system_prompt(channel: discord.abc.Messageable, client: discord.Client) -> str:
    sections = [
        build_security_section(),
        build_persona_section(),
        build_formatting_section(),
        build_capabilities_section(),
        build_search_prompt(),
        build_context_section(channel, client),
    ]
    return "\n\n---\n\n".join(sections)
