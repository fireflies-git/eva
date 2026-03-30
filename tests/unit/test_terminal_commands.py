from __future__ import annotations

import asyncio
from pathlib import Path

from eva.discord.terminal_commands import handle_terminal_command
from eva.terminal import TerminalService


def _build_terminal_service(tmp_path: Path) -> TerminalService:
    return TerminalService(
        workdir=tmp_path,
        shell="/bin/sh",
        timeout_seconds=5.0,
        max_output_chars=200,
    )


def test_terminal_command_requires_admin_or_owner(tmp_path: Path) -> None:
    response = asyncio.run(
        handle_terminal_command(
            content="eva shell pwd",
            user_id=999,
            is_owner=False,
            trigger_prefix="eva ",
            terminal_service=_build_terminal_service(tmp_path),
        )
    )

    assert response.handled is True
    assert "don't have permission" in response.content


def test_terminal_command_runs_for_admin(tmp_path: Path) -> None:
    response = asyncio.run(
        handle_terminal_command(
            content="eva shell pwd",
            user_id=218675193592283137,
            is_owner=False,
            trigger_prefix="eva ",
            terminal_service=_build_terminal_service(tmp_path),
        )
    )

    assert response.handled is True
    assert "Terminal result" in response.content
    assert str(tmp_path) in response.content


def test_terminal_command_supports_exec_alias(tmp_path: Path) -> None:
    response = asyncio.run(
        handle_terminal_command(
            content="eva exec printf 'hi'",
            user_id=218675193592283137,
            is_owner=False,
            trigger_prefix="eva ",
            terminal_service=_build_terminal_service(tmp_path),
        )
    )

    assert response.handled is True
    assert "hi" in response.content


def test_terminal_command_returns_usage_for_empty_command(tmp_path: Path) -> None:
    response = asyncio.run(
        handle_terminal_command(
            content="eva shell",
            user_id=218675193592283137,
            is_owner=False,
            trigger_prefix="eva ",
            terminal_service=_build_terminal_service(tmp_path),
        )
    )

    assert response.handled is True
    assert "Usage" in response.content
