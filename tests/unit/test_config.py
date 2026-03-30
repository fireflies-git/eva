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
