from __future__ import annotations

import asyncio
import json
import math
import os
import re
import shlex
import shutil
import signal
import stat
import subprocess  # nosec B404 - required for process-group termination.
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

from eva.terminal.schemas import TerminalCommandResult

_AUTONOMOUS_TOOL_NAME = "run_terminal_command"

# Commands that are useful for inspecting a checkout or a runtime and do not
# normally mutate it. Commands are executed directly, without a shell, so this
# list is also the first policy boundary for the autonomous tool.
_DEFAULT_ALLOWED_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "basename",
        "cat",
        "date",
        "dirname",
        "dir",
        "echo",
        "false",
        "file",
        "find",
        "grep",
        "git",
        "head",
        "id",
        "ls",
        "pwd",
        "printf",
        "printenv",
        "realpath",
        "sort",
        "stat",
        "tail",
        "true",
        "uname",
        "wc",
        "which",
        "where",
        "whoami",
        # Useful for checking timeout handling. It cannot access the network
        # or mutate the working directory by itself.
        "sleep",
        "timeout",
        # Interpreters are accepted only for harmless version checks below;
        # scripts and -c/-m execution are explicitly rejected.
        "python",
        "python3",
    }
)
_INTERPRETERS: Final[frozenset[str]] = frozenset({"python", "python3"})
_PATH_ARGUMENT_COMMANDS: Final[frozenset[str]] = frozenset(
    {
        "basename",
        "cat",
        "dirname",
        "dir",
        "file",
        "find",
        "grep",
        "head",
        "ls",
        "realpath",
        "stat",
        "sort",
        "tail",
        "wc",
    }
)
_FORBIDDEN_FIND_ARGUMENTS: Final[frozenset[str]] = frozenset(
    {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"}
)
_GIT_READ_ONLY_SUBCOMMANDS: Final[frozenset[str]] = frozenset({"status", "version"})
_GIT_STATUS_OPTIONS: Final[frozenset[str]] = frozenset(
    {"--short", "--porcelain", "--branch", "--untracked-files=no"}
)
_FORBIDDEN_SORT_OPTIONS: Final[frozenset[str]] = frozenset(
    {"-o", "--output", "--compress-program"}
)
_FORBIDDEN_DATE_OPTIONS: Final[frozenset[str]] = frozenset(
    {"-f", "--file", "-r", "--reference"}
)
_FORBIDDEN_GREP_OPTIONS: Final[frozenset[str]] = frozenset(
    {"-r", "-R", "--recursive"}
)
_SENSITIVE_PATH_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".env",
        "whitelist.db",
        "tracked_messages.json",
        "user_memory.json",
        "reminders.json",
        "pending_friend_requests.json",
        "yuri.db",
        "docker.sock",
    }
)
_SHELL_OPERATOR_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:&&|\|\||[;&|><`]|\$\(|\$\{|\n|\r)"
)
_MAX_ARGUMENT_COUNT: Final[int] = 64
_MAX_ARGUMENT_LENGTH: Final[int] = 4096
_MAX_TOOL_ARGUMENTS: Final[int] = 8192


class TerminalClientError(RuntimeError):
    pass


class TerminalCommandRejectedError(TerminalClientError):
    pass


def _prepare_workdir(workdir: str | Path) -> Path:
    """Create and validate the directory exposed to terminal commands.

    The default lives below ``/tmp``, which is shared and commonly writable.
    Refuse symlinks and directories owned by another user so an attacker cannot
    replace the configured path with a link to application state or secrets.
    """

    raw = Path(workdir).expanduser()
    if "\x00" in str(raw):
        raise TerminalClientError("Terminal workdir contains a NUL byte")
    candidate = Path(os.path.abspath(raw))

    for component in (candidate, *candidate.parents):
        if component.is_symlink():
            raise TerminalClientError("Terminal workdir must not contain symlinks")

    try:
        candidate.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise TerminalClientError("Terminal workdir could not be created") from exc

    if candidate.is_symlink() or not candidate.is_dir():
        raise TerminalClientError("Terminal workdir must be a real directory")

    if os.name != "nt":
        try:
            metadata = candidate.stat()
            current_uid = getattr(os, "getuid", lambda: metadata.st_uid)()
            if metadata.st_uid != current_uid:
                raise TerminalClientError("Terminal workdir is owned by another user")
            if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                candidate.chmod(stat.S_IRWXU)
        except OSError as exc:
            raise TerminalClientError("Terminal workdir could not be inspected") from exc

    return candidate.resolve()


class TerminalService:
    """Run tightly constrained inspection commands in a working directory.

    The old implementation handed an arbitrary string to ``shell -lc``. This
    service tokenizes the command and invokes the selected executable directly.
    That makes command chains, redirects, command substitution, and shell
    startup files unavailable to model-generated calls.

    ``require_sandbox`` can be enabled by the application when bubblewrap is
    installed. The sandbox has no network namespace and sees only the working
    directory plus read-only system directories. Unsupported hosts fail closed
    when this option is requested.
    """

    def __init__(
        self,
        *,
        workdir: str | Path,
        shell: str,
        timeout_seconds: float,
        max_output_chars: int,
        max_command_chars: int = 2048,
        allowed_commands: Sequence[str] | None = None,
        require_sandbox: bool = False,
        sandbox_executable: str | Path | None = None,
        max_processes: int = 32,
        max_file_size_bytes: int = 8 * 1024 * 1024,
        max_memory_bytes: int = 512 * 1024 * 1024,
    ) -> None:
        self._workdir = _prepare_workdir(workdir)
        # Kept in the constructor for compatibility with explicit terminal
        # settings. Commands are no longer passed through this shell.
        self._shell = shell
        self._timeout_seconds = max(0.001, timeout_seconds)
        self._max_output_chars = max(0, max_output_chars)
        self._max_command_chars = max(1, max_command_chars)
        self._allowed_commands = frozenset(
            command.strip().lower()
            for command in (allowed_commands or _DEFAULT_ALLOWED_COMMANDS)
            if command.strip()
        )
        self._require_sandbox = require_sandbox
        self._sandbox_executable = str(sandbox_executable) if sandbox_executable else None
        self._max_processes = max(1, max_processes)
        self._max_file_size_bytes = max(1, max_file_size_bytes)
        self._max_memory_bytes = max(1, max_memory_bytes)
        self._safe_environment = _build_safe_environment(self._workdir)

    async def run(self, command: str) -> TerminalCommandResult:
        return await self._run_command(command)

    async def run_read_only(self, command: str) -> TerminalCommandResult:
        return await self._run_command(command)

    async def run_autonomous_tool(self, arguments: str) -> str:
        if len(arguments) > _MAX_TOOL_ARGUMENTS:
            raise TerminalCommandRejectedError("Tool arguments are too large.")
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
                    "Run one approved read-only inspection command in Eva's isolated working "
                    "directory. Commands are executed without a shell and without network "
                    "access. Do not use pipes, command chains, redirects, command substitution, "
                    "package managers, installers, or commands that modify files. Output and "
                    "runtime are bounded."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": (
                                "One read-only command such as `pwd`, `ls`, `git status`, "
                                "or `python --version`. Shell operators, redirection, pipes, "
                                "and scripts are not supported."
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
        trimmed, argv = self._validate_command(command)
        try:
            workdir = self._workdir.resolve(strict=True)
        except FileNotFoundError as exc:
            raise TerminalClientError(f"Terminal workdir does not exist: {self._workdir}") from exc
        if not workdir.is_dir():
            raise TerminalClientError(f"Terminal workdir is not a directory: {workdir}")

        executable = shutil.which(argv[0], path=self._safe_environment.get("PATH"))
        if executable is None:
            raise TerminalCommandRejectedError(f"Command is not available: {argv[0]}")

        process_argv = self._build_process_argv(argv=argv, executable=executable, workdir=workdir)
        try:
            # ``asyncio`` exposes platform-specific subprocess keyword
            # arguments that the type stubs cannot express as one mapping.
            create_process = cast(Any, asyncio.create_subprocess_exec)
            process = await create_process(
                *process_argv,
                cwd=str(workdir),
                env=self._safe_environment,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **_process_group_kwargs(),
                **_resource_limit_kwargs(
                    timeout_seconds=self._timeout_seconds,
                    max_processes=self._max_processes,
                    max_file_size_bytes=self._max_file_size_bytes,
                    max_memory_bytes=self._max_memory_bytes,
                ),
            )
        except OSError as exc:
            raise TerminalClientError(f"Failed to start terminal command: {exc}") from exc

        output_limit_event = asyncio.Event()
        stdout_buffer: bytearray = bytearray()
        stderr_buffer: bytearray = bytearray()
        stdout_task = asyncio.create_task(
            _collect_stream(
                process.stdout,
                stdout_buffer,
                stderr_buffer,
                output_limit_event,
                self._max_output_chars,
            )
        )
        stderr_task = asyncio.create_task(
            _collect_stream(
                process.stderr,
                stderr_buffer,
                stdout_buffer,
                output_limit_event,
                self._max_output_chars,
            )
        )
        wait_task = asyncio.create_task(process.wait())
        limit_task = asyncio.create_task(output_limit_event.wait())
        timed_out = False
        output_limited = False
        try:
            done, _ = await asyncio.wait(
                {wait_task, limit_task},
                timeout=self._timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                timed_out = True
                await _terminate_process_tree(process)
            elif limit_task in done and not wait_task.done():
                output_limited = True
                await _terminate_process_tree(process)
            if not wait_task.done():
                await wait_task
        finally:
            limit_task.cancel()
            await _cancel_task(limit_task)
            if not wait_task.done():
                wait_task.cancel()
                await _cancel_task(wait_task)
            await _finish_stream_tasks(stdout_task, stderr_task)

        stdout = bytes(stdout_buffer).decode("utf-8", errors="replace")
        stderr = bytes(stderr_buffer).decode("utf-8", errors="replace")
        stdout, stderr, truncated = _truncate_output(
            stdout=stdout,
            stderr=stderr,
            max_output_chars=self._max_output_chars,
        )
        truncated = truncated or output_limited

        return TerminalCommandResult(
            command=trimmed,
            cwd=str(workdir),
            stdout=stdout,
            stderr=stderr,
            exit_code=None if timed_out else process.returncode,
            timed_out=timed_out,
            truncated=truncated,
        )

    def _validate_command(self, command: str) -> tuple[str, list[str]]:
        trimmed = command.strip()
        if not trimmed:
            raise TerminalCommandRejectedError("Terminal command is empty.")
        if len(trimmed) > self._max_command_chars:
            raise TerminalCommandRejectedError("Terminal command is too long.")
        if "\x00" in trimmed:
            raise TerminalCommandRejectedError("Terminal command contains a NUL byte.")
        if _SHELL_OPERATOR_RE.search(trimmed):
            raise TerminalCommandRejectedError(
                "Shell operators, pipes, redirects, and command substitution are not allowed."
            )
        try:
            argv = shlex.split(trimmed, posix=True)
        except ValueError as exc:
            raise TerminalCommandRejectedError("Terminal command has invalid quoting.") from exc
        if not argv:
            raise TerminalCommandRejectedError("Terminal command is empty.")
        if len(argv) > _MAX_ARGUMENT_COUNT or any(
            len(argument) > _MAX_ARGUMENT_LENGTH for argument in argv
        ):
            raise TerminalCommandRejectedError(
                "Terminal command has too many or oversized arguments."
            )

        executable_name = Path(argv[0]).name.lower()
        if executable_name not in self._allowed_commands:
            raise TerminalCommandRejectedError(
                f"Command is not on the read-only allowlist: {executable_name}"
            )
        if Path(argv[0]).is_absolute() or "/" in argv[0] or "\\" in argv[0]:
            raise TerminalCommandRejectedError(
                "Executable paths are not allowed; use an allowlisted name."
            )
        if executable_name in _INTERPRETERS and argv[1:] not in (
            ["--version"],
            ["-V"],
        ):
            raise TerminalCommandRejectedError(
                "Interpreter scripts are not allowed; only the version flag is supported."
            )
        if executable_name == "git":
            subcommand = argv[1].lower() if len(argv) > 1 else ""
            if subcommand not in _GIT_READ_ONLY_SUBCOMMANDS:
                raise TerminalCommandRejectedError(
                    f"Git subcommand is not read-only: {subcommand}"
                )
            if subcommand == "status" and any(
                option not in _GIT_STATUS_OPTIONS for option in argv[2:]
            ):
                raise TerminalCommandRejectedError("Git status option is not allowed.")
            if subcommand == "version" and len(argv) != 2:
                raise TerminalCommandRejectedError("Git version accepts no arguments.")
        if executable_name == "printenv" and argv[1:]:
            safe_names = {"PATH", "LANG", "LC_ALL", "PYTHONIOENCODING", "SystemRoot"}
            if any(argument not in safe_names for argument in argv[1:]):
                raise TerminalCommandRejectedError(
                    "Only safe environment names may be inspected."
                )
        if executable_name == "sort" and any(
            argument.lower().split("=", 1)[0] in _FORBIDDEN_SORT_OPTIONS
            for argument in argv[1:]
        ):
            raise TerminalCommandRejectedError("Sort output files are not allowed.")
        if executable_name == "date" and any(
            argument.lower().split("=", 1)[0] in _FORBIDDEN_DATE_OPTIONS
            for argument in argv[1:]
        ):
            raise TerminalCommandRejectedError("Date input files are not allowed.")
        if executable_name == "find" and any(
            argument.lower() in _FORBIDDEN_FIND_ARGUMENTS for argument in argv[1:]
        ):
            raise TerminalCommandRejectedError(
                "Find execution and deletion actions are not allowed."
            )
        if executable_name == "grep" and any(
            argument in _FORBIDDEN_GREP_OPTIONS for argument in argv[1:]
        ):
            raise TerminalCommandRejectedError(
                "Recursive grep is not allowed in the terminal workdir."
            )
        if executable_name in _PATH_ARGUMENT_COMMANDS:
            self._validate_path_arguments(argv[1:])
        return trimmed, argv

    def _validate_path_arguments(self, arguments: Sequence[str]) -> None:
        try:
            workdir = self._workdir.resolve()
        except OSError as exc:
            raise TerminalClientError(f"Unable to resolve terminal workdir: {exc}") from exc
        for argument in arguments:
            # Flags are generally not paths. Handle ``--flag=/path`` too,
            # since otherwise it is an easy way around the workdir boundary.
            candidate = argument.split("=", 1)[1] if "=" in argument else argument
            if candidate.startswith("-"):
                continue
            path = Path(candidate).expanduser()
            if path.is_absolute():
                resolved = path.resolve()
            else:
                resolved = (workdir / path).resolve()
            if not _is_relative_to(resolved, workdir):
                raise TerminalCommandRejectedError(
                    "Command paths must stay inside the terminal workdir."
                )
            if _is_sensitive_path(resolved, workdir):
                raise TerminalCommandRejectedError(
                    "Command paths may not access secrets or persistent state."
                )

    def _build_process_argv(
        self,
        *,
        argv: Sequence[str],
        executable: str,
        workdir: Path,
    ) -> list[str]:
        command_argv = [argv[0], *argv[1:]]
        if argv[0].lower() == "git":
            command_argv = [
                argv[0],
                "--no-pager",
                "--no-optional-locks",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.hooksPath=/dev/null",
                *argv[1:],
            ]
        if not self._require_sandbox:
            # Use the resolved executable rather than letting PATH change
            # between validation and process creation.
            return [executable, *command_argv[1:]]

        sandbox = self._sandbox_executable or shutil.which(
            "bwrap",
            path=self._safe_environment.get("PATH"),
        )
        if sandbox is None:
            raise TerminalClientError("Terminal sandbox is required but bubblewrap is unavailable.")
        if os.name != "posix":
            raise TerminalClientError("Terminal sandbox is unavailable on this host.")
        # Bind only the standard runtime directories and the dedicated working
        # directory. The host root and application secrets remain hidden.
        sandbox_args = [
            sandbox,
            "--die-with-parent",
            "--new-session",
            "--unshare-net",
            "--ro-bind",
            str(workdir),
            "/workspace",
            "--chdir",
            "/workspace",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",  # nosec B108 - sandbox tmpfs is isolated by bubblewrap.
        ]
        for directory in ("/usr", "/bin", "/lib", "/lib64", "/etc"):
            if Path(directory).exists():
                sandbox_args.extend(["--ro-bind", directory, directory])
        sandbox_args.extend(["--", *command_argv])
        return sandbox_args


def _is_sensitive_path(path: Path, workdir: Path) -> bool:
    try:
        relative_parts = path.relative_to(workdir).parts
    except ValueError:
        return True
    for part in relative_parts:
        lowered = part.lower()
        if lowered == ".git" or lowered in _SENSITIVE_PATH_NAMES:
            return True
        if lowered == ".env" or lowered.startswith(".env."):
            return True
    return False


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


def _build_safe_environment(workdir: Path) -> dict[str, str]:
    # Do not inherit the operator's PATH. It can contain a writable checkout,
    # a virtual environment, or another directory that supplies a trojan binary
    # under an allowlisted name. Keep only fixed system locations instead.
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        path_entries = [
            str(Path(sys.executable).resolve().parent),
            str(Path(system_root) / "System32"),
            system_root,
        ]
    else:
        path_entries = [
            str(Path(sys.executable).resolve().parent),
            "/usr/local/sbin",
            "/usr/local/bin",
            "/usr/sbin",
            "/usr/bin",
            "/sbin",
            "/bin",
        ]
    environment = {
        "PATH": os.pathsep.join(path_entries),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONIOENCODING": "utf-8",
        "TEMP": str(workdir),
        "TMP": str(workdir),
        "TMPDIR": str(workdir),
    }
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot")
        if system_root:
            environment["SystemRoot"] = system_root
    return {key: value for key, value in environment.items() if value}


def _process_group_kwargs() -> dict[str, object]:
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _resource_limit_kwargs(
    *,
    timeout_seconds: float,
    max_processes: int,
    max_file_size_bytes: int,
    max_memory_bytes: int,
) -> dict[str, object]:
    if os.name != "posix":
        return {}
    try:
        import resource
    except ImportError:
        return {}

    cpu_seconds = max(1, math.ceil(timeout_seconds))

    def apply_limits() -> None:
        limits: list[tuple[int, int, int]] = [
            (resource.RLIMIT_CPU, cpu_seconds, cpu_seconds + 1),
            (resource.RLIMIT_FSIZE, max_file_size_bytes, max_file_size_bytes),
            (resource.RLIMIT_NPROC, max_processes, max_processes),
            (resource.RLIMIT_AS, max_memory_bytes, max_memory_bytes),
            (resource.RLIMIT_NOFILE, 64, 64),
        ]
        for limit, soft, hard in limits:
            try:
                resource.setrlimit(limit, (soft, hard))
            except (OSError, ValueError):
                # Some limits are unavailable or already lower in restricted
                # containers. The process still has wall-clock/output caps.
                continue

    return {"preexec_fn": apply_limits}


async def _collect_stream(
    stream: asyncio.StreamReader | None,
    destination: bytearray,
    other_destination: bytearray,
    output_limit_event: asyncio.Event,
    max_output_chars: int,
) -> None:
    if stream is None:
        return
    limit = max(0, max_output_chars)
    while True:
        chunk = await stream.read(4096)
        if not chunk:
            return
        remaining = limit - len(destination) - len(other_destination)
        if remaining <= 0:
            output_limit_event.set()
            return
        destination.extend(chunk[:remaining])
        if len(chunk) > remaining:
            output_limit_event.set()
            return


async def _finish_stream_tasks(*tasks: asyncio.Task[object]) -> None:
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=1.0)
    except TimeoutError:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _cancel_task(task: asyncio.Task[object]) -> None:
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _terminate_process_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, OSError):
            try:
                process.terminate()
            except ProcessLookupError:
                return
        try:
            await asyncio.wait_for(process.wait(), timeout=0.5)
            return
        except TimeoutError:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
    else:
        try:
            # ``kill`` only terminates the direct child on Windows.  Use the
            # native taskkill tree mode first so descendants cannot survive a
            # timeout or output-limit termination.
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await asyncio.wait_for(killer.wait(), timeout=0.5)
            except TimeoutError:
                killer.kill()
                await killer.wait()
        except (FileNotFoundError, ProcessLookupError, OSError):
            try:
                process.kill()
            except ProcessLookupError:
                return
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                return
    try:
        await process.wait()
    except ProcessLookupError:
        pass


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


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
