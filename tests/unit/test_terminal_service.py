from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from eva.terminal import TerminalCommandRejectedError, TerminalService


def test_terminal_service_runs_command_and_captures_output(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    result = asyncio.run(service.run("printf 'hello world'"))

    assert result.exit_code == 0
    assert result.stdout == "hello world"
    assert result.stderr == ""
    assert result.timed_out is False
    assert result.truncated is False


def test_terminal_service_truncates_output(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=5,
    )

    result = asyncio.run(service.run("printf 'abcdefgh'"))

    assert result.stdout == "abcde"
    assert result.truncated is True


def test_terminal_service_marks_timeout(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=0.01,
        max_output_chars=200,
    )

    result = asyncio.run(service.run("sleep 0.2"))

    assert result.timed_out is True
    assert result.exit_code is None


def test_run_read_only_rejects_pipes(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="operators"):
        asyncio.run(service.run_read_only("printf 'a\\nb\\nc\\n' | head -n 1"))


def test_run_read_only_rejects_command_chains(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="operators"):
        asyncio.run(service.run_read_only("true && printf 'ok'"))


def test_run_read_only_rejects_empty_command(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError):
        asyncio.run(service.run_read_only("   "))


def test_autonomous_tool_definition_describes_read_only_policy(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    definition = service.build_autonomous_tool_definition()
    description = definition["function"]["description"]  # type: ignore[index]

    assert "read-only" in description
    assert "without a shell" in description
    assert "pipes" in description
    assert "package managers" in description


def test_run_read_only_rejects_interpreter_scripts(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="scripts"):
        asyncio.run(service.run_read_only("python -c 'print(1)'"))


def test_run_read_only_rejects_paths_outside_workdir(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="inside"):
        asyncio.run(service.run_read_only("cat ../secret.txt"))


def test_run_read_only_rejects_find_execution(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="execution"):
        asyncio.run(service.run_read_only("find . -exec echo leaked"))


def test_run_read_only_does_not_inherit_process_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVA_TEST_SECRET", "must-not-be-visible")
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    result = asyncio.run(service.run_read_only("printenv"))

    assert "EVA_TEST_SECRET" not in result.stdout
