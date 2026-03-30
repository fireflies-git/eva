from __future__ import annotations

import asyncio
import json
import shlex
from pathlib import Path

from eva.terminal.schemas import TerminalCommandResult

_AUTONOMOUS_TOOL_NAME = "run_terminal_command"
_AUTONOMOUS_PROGRAMS = {
    "cat",
    "file",
    "git",
    "grep",
    "head",
    "ls",
    "pwd",
    "readlink",
    "stat",
    "tail",
}
_AUTONOMOUS_GIT_SUBCOMMANDS = {
    "branch",
    "diff",
    "log",
    "rev-parse",
    "show",
    "status",
}
_FORBIDDEN_SHELL_SNIPPETS = ("&&", "||", ";", "|", ">", "<", "`", "$(", "\n", "\r")
_SENSITIVE_PATH_MARKERS = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    "credentials.json",
    "id_ed25519",
    "id_rsa",
}
_SENSITIVE_SUFFIXES = (".key", ".pem", ".p12", ".pfx", ".crt", ".kdbx")


class TerminalClientError(RuntimeError):
    pass


class TerminalCommandRejectedError(TerminalClientError):
    pass


class TerminalService:
    def __init__(
        self,
        *,
        workdir: str | Path,
        shell: str,
        timeout_seconds: float,
        max_output_chars: int,
    ) -> None:
        self._workdir = Path(workdir)
        self._shell = shell
        self._timeout_seconds = timeout_seconds
        self._max_output_chars = max_output_chars

    async def run(self, command: str) -> TerminalCommandResult:
        return await self._run_command(command)

    async def run_read_only(self, command: str) -> TerminalCommandResult:
        self._validate_read_only_command(command)
        return await self._run_command(command)

    async def run_autonomous_tool(self, arguments: str) -> str:
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise TerminalCommandRejectedError("Tool arguments must be valid JSON.") from exc

        if not isinstance(parsed, dict):
            raise TerminalCommandRejectedError("Tool arguments must be a JSON object.")

        command = parsed.get("command")
        if not isinstance(command, str):
            raise TerminalCommandRejectedError("Tool arguments must include a string 'command'.")

        result = await self.run_read_only(command)
        return format_terminal_result(result)

    def build_autonomous_tool_definition(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": _AUTONOMOUS_TOOL_NAME,
                "description": (
                    "Run a read-only terminal command inside the current Docker container to inspect "
                    "files, directories, and git state. Never use it to modify files, install "
                    "packages, reveal secrets, or run interactive commands."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "Read-only shell command. Allowed programs: pwd, ls, cat, head, "
                                "tail, stat, file, readlink, grep, and git status/diff/log/show/"
                                "branch/rev-parse."
                            ),
                        }
                    },
                    "required": ["command"],
                    "additionalProperties": False,
                },
            },
        }

    @property
    def autonomous_tool_name(self) -> str:
        return _AUTONOMOUS_TOOL_NAME

    async def _run_command(self, command: str) -> TerminalCommandResult:
        trimmed = command.strip()
        if not trimmed:
            raise TerminalClientError("Terminal command is empty.")
        if not self._workdir.exists():
            raise TerminalClientError(f"Terminal workdir does not exist: {self._workdir}")

        try:
            process = await asyncio.create_subprocess_exec(
                self._shell,
                "-lc",
                trimmed,
                cwd=str(self._workdir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise TerminalClientError(f"Failed to start terminal command: {exc}") from exc

        timed_out = False
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except TimeoutError:
            timed_out = True
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        stdout, stderr, truncated = _truncate_output(
            stdout=stdout,
            stderr=stderr,
            max_output_chars=self._max_output_chars,
        )

        return TerminalCommandResult(
            command=trimmed,
            cwd=str(self._workdir),
            stdout=stdout,
            stderr=stderr,
            exit_code=None if timed_out else process.returncode,
            timed_out=timed_out,
            truncated=truncated,
        )

    def _validate_read_only_command(self, command: str) -> None:
        trimmed = command.strip()
        if not trimmed:
            raise TerminalCommandRejectedError("Terminal command is empty.")

        for snippet in _FORBIDDEN_SHELL_SNIPPETS:
            if snippet in trimmed:
                raise TerminalCommandRejectedError(
                    "Only a single read-only command is allowed for autonomous terminal access."
                )

        try:
            tokens = shlex.split(trimmed)
        except ValueError as exc:
            raise TerminalCommandRejectedError(f"Invalid shell command: {exc}") from exc

        if not tokens:
            raise TerminalCommandRejectedError("Terminal command is empty.")

        program = tokens[0]
        if program not in _AUTONOMOUS_PROGRAMS:
            allowed = ", ".join(sorted(_AUTONOMOUS_PROGRAMS))
            raise TerminalCommandRejectedError(
                f"Autonomous terminal access only allows these programs: {allowed}."
            )

        if program == "git":
            self._validate_read_only_git_command(tokens)

        self._validate_sensitive_paths(tokens)

    def _validate_read_only_git_command(self, tokens: list[str]) -> None:
        if len(tokens) < 2:
            raise TerminalCommandRejectedError("Autonomous git commands must include a subcommand.")

        subcommand = tokens[1]
        if subcommand not in _AUTONOMOUS_GIT_SUBCOMMANDS:
            allowed = ", ".join(sorted(_AUTONOMOUS_GIT_SUBCOMMANDS))
            raise TerminalCommandRejectedError(
                f"Autonomous git access only allows these subcommands: {allowed}."
            )

    def _validate_sensitive_paths(self, tokens: list[str]) -> None:
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            lowered = token.lower()
            if any(marker in lowered for marker in _SENSITIVE_PATH_MARKERS):
                raise TerminalCommandRejectedError(
                    "Autonomous terminal access cannot inspect secret-bearing paths like .env or keys."
                )
            if lowered.endswith(_SENSITIVE_SUFFIXES):
                raise TerminalCommandRejectedError(
                    "Autonomous terminal access cannot inspect secret-bearing paths like .env or keys."
                )


def format_terminal_result(result: TerminalCommandResult) -> str:
    lines = [
        f"Command: {result.command}",
        f"Working directory: {result.cwd}",
    ]

    if result.timed_out:
        lines.append("Status: timed out")
    else:
        lines.append(f"Exit code: {result.exit_code}")

    stdout = result.stdout.strip()
    stderr = result.stderr.strip()

    if stdout:
        lines.extend(["", "Stdout:", stdout])
    if stderr:
        lines.extend(["", "Stderr:", stderr])
    if not stdout and not stderr:
        lines.extend(["", "(no output)"])
    if result.truncated:
        lines.extend(["", "[output truncated]"])

    return "\n".join(lines).strip()


def _truncate_output(*, stdout: str, stderr: str, max_output_chars: int) -> tuple[str, str, bool]:
    if max_output_chars <= 0:
        return "", "", bool(stdout or stderr)

    combined_len = len(stdout) + len(stderr)
    if combined_len <= max_output_chars:
        return stdout, stderr, False

    remaining = max_output_chars
    truncated_stdout = stdout[:remaining]
    remaining -= len(truncated_stdout)
    truncated_stderr = stderr[:remaining] if remaining > 0 else ""
    return truncated_stdout, truncated_stderr, True
