import os
import stat
from pathlib import Path

from eva.cli import run_settings


def test_run_settings_writes_account_mode_to_env(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = run_settings(["set", "account-mode", "standalone"])

    assert exit_code == 0
    assert "ACCOUNT_MODE='standalone'" in Path(".env").read_text(encoding="utf-8")


def test_run_settings_show_uses_default_when_unset(capsys, monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = run_settings(["show"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "account-mode: assistant" in captured.out


def test_run_settings_honors_explicit_env_path_and_restricts_permissions(
    monkeypatch, tmp_path
) -> None:
    env_path = tmp_path / "config" / ".env"
    monkeypatch.setenv("EVA_ENV_PATH", str(env_path))

    assert run_settings(["set", "account-mode", "standalone"]) == 0
    assert "ACCOUNT_MODE='standalone'" in env_path.read_text(encoding="utf-8")
    if os.name != "nt":
        assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
