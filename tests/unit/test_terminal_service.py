from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from eva.terminal import TerminalClientError, TerminalCommandRejectedError, TerminalService


def _output_command() -> str:
    if os.name == "nt":
        return "python --version"
    return "printf 'hello world'"


def _timeout_command() -> str:
    if os.name == "nt":
        return "timeout /t 1 /nobreak"
    return "sleep 0.2"


def test_terminal_service_runs_command_and_captures_output(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    result = asyncio.run(service.run(_output_command()))

    assert result.exit_code == 0
    if os.name == "nt":
        assert "Python" in result.stdout or "Python" in result.stderr
    else:
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

    result = asyncio.run(service.run(_output_command()))

    if os.name != "nt":
        assert result.stdout == "abcde"
    assert len(result.stdout) + len(result.stderr) <= 5
    assert result.truncated is True


def test_terminal_service_marks_timeout(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=0.01,
        max_output_chars=200,
    )

    result = asyncio.run(service.run(_timeout_command()))

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

    with pytest.raises(TerminalCommandRejectedError, match="scripts"):
        asyncio.run(service.run_read_only("python script.py"))


def test_run_read_only_rejects_ripgrep_preprocessor(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="allowlist"):
        asyncio.run(service.run_read_only("rg --pre python pattern"))


def test_run_read_only_rejects_paths_outside_workdir(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="inside"):
        asyncio.run(service.run_read_only("cat ../secret.txt"))


@pytest.mark.parametrize(
    "command",
    [
        "cat .env",
        "cat .env.production",
        "cat whitelist.db",
        "cat state/user_memory.json",
        "grep -r secret .",
    ],
)
def test_run_read_only_rejects_sensitive_paths_and_recursive_reads(
    tmp_path: Path, command: str
) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError):
        asyncio.run(service.run_read_only(command))


def test_run_read_only_rejects_find_execution(tmp_path: Path) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError, match="execution"):
        asyncio.run(service.run_read_only("find . -exec echo leaked"))


@pytest.mark.parametrize(
    "command",
    [
        "git -c alias.show=!echo show",
        "git diff --output=outside.txt",
        "git diff --no-index file-a file-b",
        "git -C / status",
        "date --file=../secret.txt",
        "date --reference=../secret.txt",
        "sort -o ../outside.txt input.txt",
        "sort --compress-program=sh input.txt",
        "sort -T ../outside input.txt",
    ],
)
def test_run_read_only_rejects_escape_options(tmp_path: Path, command: str) -> None:
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    with pytest.raises(TerminalCommandRejectedError):
        asyncio.run(service.run_read_only(command))


def test_run_read_only_does_not_inherit_process_secrets(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EVA_TEST_SECRET", "must-not-be-visible")
    service = TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )

    if os.name == "nt":
        assert "EVA_TEST_SECRET" not in service._safe_environment
    else:
        result = asyncio.run(service.run_read_only("printenv"))
        assert "EVA_TEST_SECRET" not in result.stdout


@pytest.mark.skipif(os.name == "nt", reason="POSIX symlink semantics are required")
def test_terminal_workdir_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "terminal"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(TerminalClientError, match="symlink"):
        TerminalService(
            workdir=link,
            shell="/bin/sh",
            timeout_seconds=5.0,
            max_output_chars=200,
        )
