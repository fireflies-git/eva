import pytest

from eva.config import ConfigError, load_settings


def test_load_settings_reads_account_mode(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("ACCOUNT_MODE", "standalone")

    settings = load_settings()

    assert settings.account_mode == "standalone"


def test_load_settings_rejects_invalid_account_mode(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")
    monkeypatch.setenv("ACCOUNT_MODE", "weirdmode")

    with pytest.raises(ConfigError, match="ACCOUNT_MODE"):
        load_settings()
