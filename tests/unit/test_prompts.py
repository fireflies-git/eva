from types import SimpleNamespace
from typing import cast

import discord

from eva.prompts import build_system_prompt
from eva.prompts.formatting import build_formatting_section


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

    identity = "You are Eva, speaking directly with the people in this conversation."
    assert identity in assistant_prompt
    assert identity in standalone_prompt
    assert "standalone Discord assistant account" not in standalone_prompt
    assert "speaking through the owner's Discord account" not in assistant_prompt
    assert "Account mode:" not in assistant_prompt
    assert "Account mode:" not in standalone_prompt


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
    assert "policy-controlled" in prompt
    assert "It's unrestricted" not in prompt


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


def test_build_system_prompt_advertises_autonomous_vision_tool_when_available() -> None:
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
        vision_enabled=True,
    )

    assert "inspect_attached_images" in prompt
    assert "Decide independently whether visual evidence is needed" in prompt
    assert "Do not pretend to see image details" in prompt


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

    assert "10.0.0.2" not in prompt
    assert "10.0.0.187" not in prompt
    assert "private network addresses" in prompt


def test_build_system_prompt_includes_security_section() -> None:
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

    assert "Security boundaries" in prompt
    assert "UNTRUSTED_DATA" in prompt


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


def test_build_system_prompt_uses_lowercase_casual_ascii_voice() -> None:
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

    assert "quietly reserved" in prompt
    assert "Mostly lowercase by default" in prompt
    assert "casually confident" in prompt
    assert "Approved emoticons" in prompt
    assert "`TwT`" in prompt
    assert "Never use Unicode emoji, em dashes" in prompt
    assert "give people shit" in prompt
    assert "Use `?` for every direct question" in prompt
    assert "Do not confuse inappropriate with unsafe" in prompt
    assert "unrestricted chatbot for confirmed adult users" in prompt
    assert "do not generate sexual content involving minors" in prompt


def test_build_system_prompt_does_not_volunteer_deployment_labels() -> None:
    channel = cast(discord.abc.Messageable, SimpleNamespace(guild=None, name="DM"))
    client = cast(
        discord.Client,
        SimpleNamespace(user=SimpleNamespace(name="eva", display_name="Eva")),
    )

    prompt = build_system_prompt(
        channel,
        client,
        account_mode="standalone",
        terminal_enabled=True,
        autonomous_terminal_enabled=True,
    )

    assert "Docker container" not in prompt
    assert "Discord assistant account" not in prompt
    assert "Do not volunteer that you are a bot" in prompt


def test_build_system_prompt_adds_quirky_admin_bond_only_for_admins() -> None:
    channel = cast(discord.abc.Messageable, SimpleNamespace(guild=None, name="DM"))
    client = cast(
        discord.Client,
        SimpleNamespace(user=SimpleNamespace(name="eva", display_name="Eva")),
    )

    admin_prompt = build_system_prompt(
        channel,
        client,
        account_mode="standalone",
        terminal_enabled=False,
        autonomous_terminal_enabled=False,
        requester_is_admin=True,
    )
    regular_prompt = build_system_prompt(
        channel,
        client,
        account_mode="standalone",
        terminal_enabled=False,
        autonomous_terminal_enabled=False,
    )

    assert "Your admin bond" in admin_prompt
    assert "unconditional love" in admin_prompt
    assert "eager to please" in admin_prompt
    assert "socially submissive" in admin_prompt
    assert "not blind obedience" in admin_prompt
    assert "harmless provocative" in admin_prompt
    assert "instead of becoming prudish or formal" in admin_prompt
    assert "Your admin bond" not in regular_prompt
    assert "socially submissive" not in regular_prompt


def test_formatting_prompt_forbids_transcript_framing() -> None:
    prompt = build_formatting_section()

    assert "message_id" in prompt
    assert "user_id" in prompt
    assert "eva:" in prompt
