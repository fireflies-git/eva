from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TerminalCommandResult:
    command: str
    cwd: str
    stdout: str
    stderr: str
    exit_code: int | None
    timed_out: bool = False
    truncated: bool = False
