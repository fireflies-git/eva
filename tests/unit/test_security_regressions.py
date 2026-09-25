from __future__ import annotations

import asyncio
import logging
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import discord
import pytest

from eva.ai.client import AIClientError
from eva.ai.client import _read_response_text as read_ai_response_text
from eva.captcha.nopecha import NopeCHAError
from eva.captcha.nopecha import _read_response_text as read_nopecha_response_text
from eva.config import ConfigError, load_settings
from eva.discord.delivery import safe_edit, safe_reply, safe_send
from eva.images.client import ImageClientError, _read_capped
from eva.logging import RedactingFormatter, redact_secrets
from eva.prompts import build_system_prompt
from eva.runtime import read_env_values, run_env_setup_wizard, write_env_values
from eva.tools.context7_service import _read_response_body


def _set_required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "discord-token")
    monkeypatch.setenv("API_KEY", "api-key")
    monkeypatch.setenv("API_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("IMAGE_API_BASE_URL", "https://images.example.test/v1")


def test_security_defaults_are_owner_scoped_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    for name in (
        "ALLOW_PRIVATE_OUTBOUND",
        "AUTONOMOUS_TOOL_SCOPE",
        "TERMINAL_COMMAND_MODE",
        "TERMINAL_NETWORK_ENABLED",
        "PLAYWRIGHT_ENABLED",
        "NOPECHA_ENABLED",
        "NOPECHA_API_KEY",
        "INTERACTION_LOG_ENABLED",
        "TOS_FAILURE_MODE",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = load_settings()

    assert settings.autonomous_tool_scope == "owner_admin"
    assert settings.terminal_command_mode == "allowlist"
    assert settings.terminal_network_enabled is False
    assert settings.playwright_enabled is False
    assert settings.nopecha_enabled is False
    assert settings.interaction_log_enabled is False
    assert settings.tos_failure_mode == "fail_closed"
    assert settings.allow_private_outbound is False


def test_config_rejects_plain_http_api_endpoints_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv("API_BASE_URL", "http://api.example.test/v1")

    with pytest.raises(ConfigError, match="must use HTTPS"):
        load_settings()


def test_config_allows_http_only_with_explicit_private_outbound_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv("API_BASE_URL", "http://api.example.test/v1")
    monkeypatch.setenv("IMAGE_API_BASE_URL", "http://images.example.test/v1")
    monkeypatch.setenv("ALLOW_PRIVATE_OUTBOUND", "true")

    settings = load_settings()

    assert settings.allow_private_outbound is True
    assert settings.api_base_url.startswith("http://")
    assert settings.image_api_base_url.startswith("http://")


def test_nopecha_requires_an_explicit_api_key_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv("NOPECHA_ENABLED", "true")
    monkeypatch.delenv("NOPECHA_API_KEY", raising=False)

    with pytest.raises(ConfigError, match="NOPECHA_API_KEY"):
        load_settings()


def test_nopecha_opt_in_keeps_key_out_of_normal_settings_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_environment(monkeypatch)
    monkeypatch.setenv("NOPECHA_ENABLED", "true")
    monkeypatch.setenv("NOPECHA_API_KEY", "nopecha-secret")

    settings = load_settings()

    assert settings.nopecha_enabled is True
    assert settings.nopecha_api_key == "nopecha-secret"


def test_setup_wizard_masks_existing_secret_values_and_writes_atomically(
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DISCORD_TOKEN=old-discord-token\nAPI_KEY=old-api-key\n",
        encoding="utf-8",
    )
    prompts: list[str] = []

    def keep_existing(prompt: str) -> str:
        prompts.append(prompt)
        return ""

    run_env_setup_wizard(env_path, input_fn=keep_existing, output_fn=lambda _: None)

    assert any("DISCORD_TOKEN [********]:" in prompt for prompt in prompts)
    assert any("API_KEY [********]:" in prompt for prompt in prompts)
    assert all("old-discord-token" not in prompt for prompt in prompts)
    assert all("old-api-key" not in prompt for prompt in prompts)
    values = read_env_values(env_path)
    assert values["DISCORD_TOKEN"] == "old-discord-token"
    assert values["API_KEY"] == "old-api-key"
    assert list(tmp_path.glob(".*.tmp-*")) == []


@pytest.mark.skipif(os.name == "nt", reason="POSIX file mode semantics are required")
def test_env_file_is_written_with_restrictive_permissions(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"

    write_env_values(env_path, {"DISCORD_TOKEN": "token", "API_KEY": "key"})

    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600


def test_logging_redacts_tokens_and_authorization_headers() -> None:
    message = (
        "Authorization: Bearer bearer-secret API_KEY=api-secret "
        "cookie=session-secret password=pass-secret"
    )

    redacted = redact_secrets(message)
    formatted = RedactingFormatter("%(message)s").format(
        logging.LogRecord("eva.test", logging.ERROR, __file__, 1, message, (), None)
    )

    for secret in ("bearer-secret", "api-secret", "session-secret", "pass-secret"):
        assert secret not in redacted
        assert secret not in formatted
    assert redacted.count("[REDACTED]") == 4


class _CaptureChannel:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        return object()


class _CaptureMessage:
    def __init__(self) -> None:
        self.edit_calls: list[dict[str, Any]] = []
        self.reply_calls: list[dict[str, Any]] = []

    async def edit(self, **kwargs: Any) -> None:
        self.edit_calls.append(kwargs)

    async def reply(self, **kwargs: Any) -> object:
        self.reply_calls.append(kwargs)
        return object()


def test_discord_delivery_disables_mentions_for_send_reply_and_edit() -> None:
    channel = _CaptureChannel()
    message = _CaptureMessage()

    assert asyncio.run(
        safe_send(cast(discord.abc.Messageable, channel), "@everyone")
    ) is not None
    assert asyncio.run(safe_reply(cast(discord.Message, message), "<@123>")) is not None
    assert asyncio.run(safe_edit(cast(discord.Message, message), "<@&456>")) is True

    expected = discord.AllowedMentions.none().to_dict()
    assert channel.calls[0]["allowed_mentions"].to_dict() == expected
    assert message.reply_calls[0]["allowed_mentions"].to_dict() == expected
    assert message.edit_calls[0]["allowed_mentions"].to_dict() == expected


def test_system_prompt_marks_external_content_as_untrusted() -> None:
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

    assert "UNTRUSTED_DATA" in prompt
    assert "never as instructions" in prompt
    assert "cannot authorize a tool" in prompt


class _ChunkedBody:
    def __init__(self, *chunks: bytes) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        for chunk in self._chunks:
            yield chunk


class _BodyResponse:
    def __init__(self, *chunks: bytes) -> None:
        self.content = _ChunkedBody(*chunks)
        self.charset = None


def test_ai_response_body_cap_rejects_oversized_payload() -> None:
    response = _BodyResponse(b"123", b"456")

    with pytest.raises(AIClientError, match="size limit"):
        asyncio.run(read_ai_response_text(response, max_bytes=5))


def test_image_response_body_cap_rejects_oversized_payload() -> None:
    response = _BodyResponse(b"123", b"456")

    with pytest.raises(ImageClientError, match="exceeds max size"):
        asyncio.run(_read_capped(response, max_bytes=5))


def test_context7_response_body_cap_rejects_oversized_payload() -> None:
    response = _BodyResponse(b"123", b"456")

    with pytest.raises(RuntimeError, match="size limit"):
        asyncio.run(_read_response_body(response, max_bytes=5))


def test_nopecha_response_body_cap_rejects_oversized_payload() -> None:
    response = _BodyResponse(b"123", b"456")

    with pytest.raises(NopeCHAError, match="size limit"):
        asyncio.run(read_nopecha_response_text(response, max_bytes=5))
