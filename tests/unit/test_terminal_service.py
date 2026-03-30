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

    result = asyncio.run(service.run('python -c "import time; time.sleep(0.2)"'))

    assert result.timed_out is True
    assert result.exit_code is None


def test_terminal_service_rejects_mutating_autonomous_commands(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="Only a single read-only command"):
        asyncio.run(service.run_read_only("ls && touch nope"))


def test_terminal_service_rejects_sensitive_autonomous_paths(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="secret-bearing paths"):
        asyncio.run(service.run_read_only("cat .env"))
