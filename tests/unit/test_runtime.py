from __future__ import annotations

import sys
from pathlib import Path

from eva.runtime import (
    apply_menu_key,
    get_env_search_paths,
    get_resolved_env_path,
    is_linux_service_mode,
    run_env_setup_wizard,
    show_interaction_logs,
    tail_text_file,
)


def test_is_linux_service_mode_detects_systemd_marker(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("INVOCATION_ID", "abc")

    assert is_linux_service_mode() is True


def test_is_linux_service_mode_false_on_non_linux(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")

    assert is_linux_service_mode() is False


def test_run_env_setup_wizard_writes_required_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    answers = iter(["token", "key", "", "", "", "", "", "", "", "", "", ""])
    output: list[str] = []

    run_env_setup_wizard(
        env_path,
        input_fn=lambda prompt: next(answers),
        output_fn=output.append,
    )

    content = env_path.read_text(encoding="utf-8")
    assert "DISCORD_TOKEN=token" in content
    assert "API_KEY=key" in content


def test_tail_text_file_returns_latest_lines(tmp_path: Path) -> None:
    log_path = tmp_path / "log.txt"
    log_path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    lines = tail_text_file(log_path, lines=2)

    assert lines == ["two", "three"]


def test_show_interaction_logs_handles_missing_file(tmp_path: Path) -> None:
    lines: list[str] = []

    show_interaction_logs(tmp_path / "missing.log", lines=10, output_fn=lines.append)

    assert len(lines) == 1
    assert "No interaction logs found" in lines[0]


def test_menu_key_wraps_up_and_down() -> None:
    assert apply_menu_key(selected=0, key="up", options_count=4) == 3
    assert apply_menu_key(selected=3, key="down", options_count=4) == 0


def test_resolved_env_path_prefers_explicit_env_path(monkeypatch, tmp_path: Path) -> None:
    explicit = tmp_path / "custom.env"
    explicit.write_text("DISCORD_TOKEN=a\nAPI_KEY=b\n", encoding="utf-8")
    monkeypatch.setenv("EVA_ENV_PATH", str(explicit))

    search_paths = get_env_search_paths()
    resolved = get_resolved_env_path()

    assert search_paths == [explicit.resolve()]
    assert resolved == explicit.resolve()
