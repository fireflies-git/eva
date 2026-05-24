from types import SimpleNamespace
from typing import cast

import discord

from eva.prompts import build_system_prompt


def test_build_system_prompt_changes_identity_by_account_mode() -> None:
    channel = cast(discord.abc.Messageable, SimpleNamespace(guild=None, name="DM"))
    client = cast(
        discord.Client,
        SimpleNamespace(user=SimpleNamespace(name="eva", display_name="Eva")),
    )

    assistant_prompt = build_system_prompt(
        channel,
        client,
        account_mode="assistant",
        terminal_enabled=True,
        autonomous_terminal_enabled=True,
    )
    standalone_prompt = build_system_prompt(
        channel,
        client,
        account_mode="standalone",
        terminal_enabled=True,
        autonomous_terminal_enabled=True,
    )

    assert "speaking through the owner's Discord account" in assistant_prompt
    assert "standalone Discord assistant account" in standalone_prompt
    assert "Account mode: assistant" in assistant_prompt
    assert "Account mode: standalone" in standalone_prompt


def test_build_system_prompt_advertises_terminal_tool_when_enabled() -> None:
    channel = cast(discord.abc.Messageable, SimpleNamespace(guild=None, name="DM"))
    client = cast(
        discord.Client,
        SimpleNamespace(user=SimpleNamespace(name="eva", display_name="Eva")),
    )

    prompt = build_system_prompt(
        channel,
        client,
        account_mode="assistant",
        terminal_enabled=True,
        autonomous_terminal_enabled=True,
    )

    assert "run_terminal_command" in prompt
    assert "unrestricted" in prompt


def test_build_system_prompt_omits_terminal_capability_when_disabled() -> None:
    channel = cast(discord.abc.Messageable, SimpleNamespace(guild=None, name="DM"))
    client = cast(
        discord.Client,
        SimpleNamespace(user=SimpleNamespace(name="eva", display_name="Eva")),
    )

    prompt = build_system_prompt(
        channel,
        client,
        account_mode="assistant",
        terminal_enabled=False,
        autonomous_terminal_enabled=False,
    )

    assert "run_terminal_command" not in prompt
    assert "don't have shell or network access" in prompt


def test_build_system_prompt_includes_home_network() -> None:
    channel = cast(discord.abc.Messageable, SimpleNamespace(guild=None, name="DM"))
    client = cast(
        discord.Client,
        SimpleNamespace(user=SimpleNamespace(name="eva", display_name="Eva")),
    )

    prompt = build_system_prompt(
        channel,
        client,
        account_mode="assistant",
        terminal_enabled=True,
        autonomous_terminal_enabled=True,
    )

    assert "boston" in prompt
    assert "10.0.0.2" in prompt
    assert "seattle" in prompt
    assert "10.0.0.187" in prompt


def test_build_system_prompt_drops_old_security_section() -> None:
    channel = cast(discord.abc.Messageable, SimpleNamespace(guild=None, name="DM"))
    client = cast(
        discord.Client,
        SimpleNamespace(user=SimpleNamespace(name="eva", display_name="Eva")),
    )

    prompt = build_system_prompt(
        channel,
        client,
        account_mode="assistant",
        terminal_enabled=True,
        autonomous_terminal_enabled=True,
    )

    assert "Security Rules" not in prompt
    assert "UNDER NO CIRCUMSTANCES" not in prompt


def test_build_system_prompt_enforces_brevity_default() -> None:
    channel = cast(discord.abc.Messageable, SimpleNamespace(guild=None, name="DM"))
    client = cast(
        discord.Client,
        SimpleNamespace(user=SimpleNamespace(name="eva", display_name="Eva")),
    )

    prompt = build_system_prompt(
        channel,
        client,
        account_mode="assistant",
        terminal_enabled=True,
        autonomous_terminal_enabled=True,
    )

    assert "Short is the default" in prompt
