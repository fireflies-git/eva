import pytest

from eva.config import ConfigError, load_settings


def test_load_settings_reads_account_mode(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("ACCOUNT_MODE", "standalone")

    settings = load_settings()

    assert settings.account_mode == "standalone"
    assert settings.terminal_enabled is True
    assert settings.terminal_autonomous_enabled is True


def test_load_settings_rejects_invalid_account_mode(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("ACCOUNT_MODE", "weirdmode")

    with pytest.raises(ConfigError, match="ACCOUNT_MODE"):
        load_settings()


def test_load_settings_reads_terminal_configuration(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("TERMINAL_ENABLED", "false")
    monkeypatch.setenv("TERMINAL_AUTONOMOUS_ENABLED", "false")
    monkeypatch.setenv("TERMINAL_WORKDIR", "/workspace")
    monkeypatch.setenv("TERMINAL_SHELL", "/bin/bash")
    monkeypatch.setenv("TERMINAL_TIMEOUT_SECONDS", "25")
    monkeypatch.setenv("TERMINAL_MAX_OUTPUT_CHARS", "4096")

    settings = load_settings()

    assert settings.terminal_enabled is False
    assert settings.terminal_autonomous_enabled is False
    assert settings.terminal_workdir == "/workspace"
    assert settings.terminal_shell == "/bin/bash"
    assert settings.terminal_timeout_seconds == 25.0
    assert settings.terminal_max_output_chars == 4096


def test_load_settings_preserves_default_trigger_prefix_space(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.delenv("TRIGGER_PREFIX", raising=False)

    settings = load_settings()

    # The trailing space is the word boundary; stripping it would make any
    # "eva..." word ("evacuate", "evaluate") trigger the bot.
    assert settings.trigger_prefix == "eva "


def test_load_settings_preserves_configured_prefix_trailing_space(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("TRIGGER_PREFIX", "hey eva ")

    settings = load_settings()

    assert settings.trigger_prefix == "hey eva "


def test_load_settings_falls_back_when_prefix_empty(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("TRIGGER_PREFIX", "")

    settings = load_settings()

    assert settings.trigger_prefix == "eva "


def test_load_settings_defaults_tos_model_to_main_model(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("MODEL_NAME", "deepseek-v4-flash")
    monkeypatch.delenv("TOS_MODEL_NAME", raising=False)

    settings = load_settings()

    assert settings.tos_model_name == "deepseek-v4-flash"


def test_load_settings_defaults_split_model_to_main_model(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("MODEL_NAME", "deepseek-v4-flash")
    monkeypatch.delenv("SPLIT_MODEL_NAME", raising=False)

    settings = load_settings()

    assert settings.split_model_name == "deepseek-v4-flash"


def test_load_settings_reads_tos_model_override(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("MODEL_NAME", "deepseek-v4-flash")
    monkeypatch.setenv("TOS_MODEL_NAME", "some-moderation-model")

    settings = load_settings()

    assert settings.tos_model_name == "some-moderation-model"


def test_load_settings_defaults_state_dir_to_cwd(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.delenv("STATE_DIR", raising=False)

    settings = load_settings()

    assert settings.state_dir == "."


def test_load_settings_reads_state_dir(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("STATE_DIR", "/app/state")

    settings = load_settings()

    assert settings.state_dir == "/app/state"


def test_load_settings_defaults_nopecha_configuration(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.delenv("NOPECHA_ENABLED", raising=False)
    monkeypatch.delenv("NOPECHA_API_KEY", raising=False)

    settings = load_settings()

    assert settings.nopecha_enabled is False
    assert settings.nopecha_api_key is None


def test_load_settings_reads_nopecha_configuration(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("NOPECHA_ENABLED", "false")
    monkeypatch.setenv("NOPECHA_API_KEY", "key123")

    settings = load_settings()

    assert settings.nopecha_enabled is False
    assert settings.nopecha_api_key == "key123"


def test_load_settings_parses_outbound_host_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("OUTBOUND_ALLOWED_HOSTS", "API.EXAMPLE.COM, docs.example.com")

    settings = load_settings()

    assert settings.outbound_allowed_hosts == frozenset(
        {"api.example.com", "docs.example.com"}
    )


def test_load_settings_rejects_url_in_outbound_host_allowlist(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("OUTBOUND_ALLOWED_HOSTS", "https://example.com")

    with pytest.raises(ConfigError, match="hostnames only"):
        load_settings()


def test_load_settings_rejects_terminal_network_override(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("TERMINAL_NETWORK_ENABLED", "true")

    with pytest.raises(ConfigError, match="TERMINAL_NETWORK_ENABLED"):
        load_settings()


def test_load_settings_accepts_disabled_autonomous_tool_scope(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("AUTONOMOUS_TOOL_SCOPE", "disabled")

    settings = load_settings()

    assert settings.autonomous_tool_scope == "disabled"


def test_load_settings_validates_admin_ids(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("ADMIN_USER_IDS", "123, invalid")

    with pytest.raises(ConfigError, match="ADMIN_USER_IDS"):
        load_settings()
