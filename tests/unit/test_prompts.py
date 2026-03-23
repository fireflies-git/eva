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

    assistant_prompt = build_system_prompt(channel, client, account_mode="assistant")
    standalone_prompt = build_system_prompt(channel, client, account_mode="standalone")

    assert "speaking through the owner's Discord account" in assistant_prompt
    assert "standalone Discord assistant account" in standalone_prompt
    assert "Account mode: assistant" in assistant_prompt
    assert "Account mode: standalone" in standalone_prompt
