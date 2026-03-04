"""Runtime context for the system prompt."""

from __future__ import annotations

from datetime import UTC, datetime

import discord


def build_context_section(channel: discord.abc.Messageable, client: discord.Client) -> str:
    guild = getattr(channel, "guild", None)
    server_name = guild.name if guild else "DM"
    channel_name = getattr(channel, "name", "DM")
    owner = guild.owner.display_name if guild and guild.owner else "Unknown"
    current_time = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    user = client.user

    return (
        "## Runtime Context\n"
        f"- Owner username: {getattr(user, 'name', 'unknown')}\n"
        f"- Owner display name: {getattr(user, 'display_name', 'unknown')}\n"
        f"- Server: {server_name}\n"
        f"- Server owner: {owner}\n"
        f"- Channel: #{channel_name}\n"
        f"- Current time: {current_time}"
    )
