from __future__ import annotations

import asyncio
import json
from pathlib import Path

from eva.terminal.schemas import TerminalCommandResult

_AUTONOMOUS_TOOL_NAME = "run_terminal_command"


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
        if not command.strip():
            raise TerminalCommandRejectedError("Terminal command is empty.")
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
                    "Run a shell command inside Eva's Docker container. Arbitrary commands are "
                    "allowed — curl, ping, pipes, redirects, command chains, anything. Use it "
                    "freely whenever it would help answer the user or check on infrastructure."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "Any shell command. Pipes, &&, ||, redirects, and tools like "
                                "curl, ping, jq, awk are all available."
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
