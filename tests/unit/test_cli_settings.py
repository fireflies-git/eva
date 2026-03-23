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
