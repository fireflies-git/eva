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


def test_run_read_only_allows_pipes(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    result = asyncio.run(service.run_read_only("printf 'a\\nb\\nc\\n' | head -n 1"))

    assert result.exit_code == 0
    assert result.stdout.strip() == "a"


def test_run_read_only_allows_command_chains(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    result = asyncio.run(service.run_read_only("true && printf 'ok'"))

    assert result.exit_code == 0
    assert result.stdout == "ok"


def test_run_read_only_rejects_empty_command(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError):
        asyncio.run(service.run_read_only("   "))


def test_autonomous_tool_definition_advertises_arbitrary_shell(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    definition = service.build_autonomous_tool_definition()
    description = definition["function"]["description"]  # type: ignore[index]

    assert "curl" in description
    assert "ping" in description
    assert "pipes" in description
