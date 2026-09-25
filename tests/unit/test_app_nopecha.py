from __future__ import annotations

from pathlib import Path
from typing import cast

import discord
import pytest

import eva.app as app_module
from eva.app import EvaApp
from eva.captcha import NopeCHAClient
from eva.config import load_settings
from eva.discord.client import CaptchaHandler
from eva.discord.handlers import SelfbotMessageHandler


@pytest.mark.parametrize("enabled", [True, False])
def test_app_wires_keyless_nopecha_only_when_enabled(
    enabled: bool,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "test-token")
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("STATE_DIR", str(tmp_path))
    monkeypatch.setenv("TERMINAL_ENABLED", "false")
    monkeypatch.setenv("NOPECHA_ENABLED", str(enabled).lower())
    monkeypatch.delenv("NOPECHA_API_KEY", raising=False)
    captured_handlers: list[CaptchaHandler | None] = []

    def fake_create_discord_client(
        handler: SelfbotMessageHandler,
        *,
        captcha_handler: CaptchaHandler | None = None,
    ) -> discord.Client:
        captured_handlers.append(captcha_handler)
        return cast(discord.Client, object())

    monkeypatch.setattr(app_module, "create_discord_client", fake_create_discord_client)

    app = EvaApp(settings=load_settings())
    try:
        assert len(captured_handlers) == 1
        captcha_handler = captured_handlers[0]
        if enabled:
            assert isinstance(app._captcha_client, NopeCHAClient)
            assert captcha_handler == app._captcha_client.handle_captcha
        else:
            assert app._captcha_client is None
            assert captcha_handler is None
    finally:
        app._whitelist.close()
