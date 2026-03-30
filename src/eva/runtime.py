from __future__ import annotations

import os
import shutil
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from colorama import Fore, Style
from colorama import init as colorama_init

_ASCII_LOGO = (
    " ___  __   __   __ _ ",
    "/ _ \\ \\ \\ / /  / _` |",
    "|  __/  \\ V /  | (_| |",
    " \\___|   \\_/    \\__,_|",
)

_COLOR_BLUE = Fore.CYAN
_COLOR_PURPLE = Fore.MAGENTA
_COLOR_DIM = Fore.BLUE
_COLOR_RESET = Style.RESET_ALL

MenuReader = Callable[[], str]
MenuWriter = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class EnvField:
    key: str
    default: str
    required: bool
    description: str


ENV_FIELDS: tuple[EnvField, ...] = (
    EnvField("DISCORD_TOKEN", "", True, "Discord user token"),
    EnvField("API_KEY", "", True, "AI API key"),
    EnvField("API_BASE_URL", "https://inference.do-ai.run/v1", False, "AI API base URL"),
    EnvField("ACCOUNT_MODE", "assistant", False, "assistant or standalone mode"),
    EnvField("MODEL_NAME", "openai-gpt-oss-120b", False, "AI model name"),
    EnvField("SPLIT_MODEL_NAME", "llama3.3-70b-instruct", False, "Follow-up split planner model"),
    EnvField("TRIGGER_PREFIX", "eva ", False, "Prefix used to trigger Eva"),
    EnvField(
        "RESPONSE_CONTEXT_MESSAGES",
        "40",
        False,
        "How many recent channel messages to include",
    ),
    EnvField("FOLLOWUP_DELAY_MIN_SECONDS", "0.75", False, "Minimum standalone follow-up delay"),
    EnvField("FOLLOWUP_DELAY_MAX_SECONDS", "1.5", False, "Maximum standalone follow-up delay"),
    EnvField("SERPER_API_KEY", "", False, "Serper API key (optional)"),
    EnvField("IMAGE_API_KEY", "", False, "Image API key (optional)"),
    EnvField("IMAGE_API_BASE_URL", "https://ai.6969.pro/v1", False, "Image API base URL"),
    EnvField("IMAGE_MODEL_NAME", "sonar", False, "Image model name"),
    EnvField("IMAGE_LANGUAGE", "en-US", False, "Image generation language"),
    EnvField("IMAGE_INCOGNITO", "true", False, "Image generation incognito mode"),
    EnvField("TERMINAL_ENABLED", "true", False, "Enable terminal access features"),
    EnvField(
        "TERMINAL_AUTONOMOUS_ENABLED",
        "true",
        False,
        "Allow read-only terminal tool use during normal replies",
    ),
    EnvField("TERMINAL_WORKDIR", "/app", False, "Working directory for terminal commands"),
    EnvField("TERMINAL_SHELL", "/bin/sh", False, "Shell used for terminal commands"),
    EnvField("TERMINAL_TIMEOUT_SECONDS", "15", False, "Timeout for terminal commands"),
    EnvField("TERMINAL_MAX_OUTPUT_CHARS", "6000", False, "Max terminal output to capture"),
)


def is_linux_service_mode() -> bool:
    if not sys.platform.startswith("linux"):
        return False

    systemd_markers = (
        os.getenv("INVOCATION_ID"),
        os.getenv("JOURNAL_STREAM"),
        os.getenv("SYSTEMD_EXEC_PID"),
    )
    if any(marker for marker in systemd_markers):
        return True

    return not sys.stdin.isatty() and not sys.stdout.isatty()


def get_env_search_paths() -> list[Path]:
    explicit = os.getenv("EVA_ENV_PATH", "").strip()
    if explicit:
        return [Path(explicit).expanduser().resolve()]

    raw_candidates: list[Path] = []

    executable_dir = _runtime_executable_dir()
    if executable_dir is not None:
        raw_candidates.append(executable_dir / ".env")

    raw_candidates.extend(
        [
            Path.cwd() / ".env",
            Path(sys.argv[0]).resolve().parent / ".env",
            Path(__file__).resolve().parents[2] / ".env",
        ]
    )

    unique: list[Path] = []
    seen: set[Path] = set()
    for path in raw_candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def get_resolved_env_path() -> Path:
    for path in get_env_search_paths():
        if path.exists():
            return path
    return _default_env_write_path()


def _default_env_write_path() -> Path:
    explicit = os.getenv("EVA_ENV_PATH", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    executable_dir = _runtime_executable_dir()
    if executable_dir is not None:
        return executable_dir / ".env"
    return (Path.cwd() / ".env").resolve()


def _runtime_executable_dir() -> Path | None:
    executable = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        return executable.parent

    name = executable.name.lower()
    if name.startswith("python") or name.startswith("uv"):
        return None
    if executable.suffix.lower() == ".exe":
        return executable.parent
    return None


def read_env_values(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_env_values(env_path: Path, values: dict[str, str]) -> None:
    lines = [
        "# Generated by Eva setup wizard",
        "# Edit values as needed",
        "",
    ]
    for field in ENV_FIELDS:
        lines.append(f"# {field.description}")
        lines.append(f"{field.key}={values.get(field.key, field.default)}")
        lines.append("")

    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def run_env_setup_wizard(
    env_path: Path,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> None:
    existing = read_env_values(env_path)
    output_fn(f"Eva environment setup ({env_path})")
    output_fn("Press Enter to keep the current value shown in [brackets].")

    updated = dict(existing)
    for field in ENV_FIELDS:
        current = existing.get(field.key, field.default)
        prompt = f"{field.key} [{current}]: "
        response = input_fn(prompt).strip()
        value = response if response else current

        while field.required and not value:
            output_fn(f"{field.key} is required.")
            response = input_fn(prompt).strip()
            value = response if response else current

        updated[field.key] = value

    write_env_values(env_path, updated)
    output_fn(f"Saved environment file: {env_path}")


def tail_text_file(path: Path, *, lines: int) -> list[str]:
    if lines <= 0:
        return []
    if not path.exists():
        return []

    content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return content[-lines:]


def show_interaction_logs(
    log_path: Path,
    *,
    lines: int,
    output_fn: Callable[[str], None] = print,
) -> None:
    entries = tail_text_file(log_path, lines=lines)
    if not entries:
        output_fn(f"No interaction logs found at {log_path}")
        return

    output_fn(f"Showing last {len(entries)} interaction log lines from {log_path}")
    for entry in entries:
        output_fn(entry)


def run_menu(
    *,
    options: Sequence[str],
    read_key: MenuReader,
    write: MenuWriter | None = None,
) -> int:
    resolved_write = write or _stdout_write
    supports_ansi = _enable_ansi_if_supported()
    selected = 0

    while True:
        _render_menu(
            options=options,
            selected=selected,
            write=resolved_write,
            supports_ansi=supports_ansi,
        )
        key = read_key()
        selected = apply_menu_key(selected=selected, key=key, options_count=len(options))
        if key == "enter":
            _show_cursor(write=resolved_write)
            return selected


def apply_menu_key(*, selected: int, key: str, options_count: int) -> int:
    if options_count <= 0:
        return 0
    if key == "up":
        return (selected - 1) % options_count
    if key == "down":
        return (selected + 1) % options_count
    return selected


def read_menu_key() -> str:
    if sys.platform.startswith("win"):
        return _read_menu_key_windows()
    return _read_menu_key_posix()


def _render_menu(
    *,
    options: Sequence[str],
    selected: int,
    write: MenuWriter,
    supports_ansi: bool,
) -> None:
    width = shutil.get_terminal_size((80, 24)).columns
    height = shutil.get_terminal_size((80, 24)).lines

    frame = _build_menu_frame(
        options=options,
        selected=selected,
        width=width,
        height=height,
        supports_ansi=supports_ansi,
    )

    if supports_ansi:
        _hide_cursor(write=write)
    _write_screen(frame=frame, write=write, supports_ansi=supports_ansi)


def _write_screen(*, frame: Sequence[str], write: MenuWriter, supports_ansi: bool) -> None:
    content = "\n".join(frame)
    if supports_ansi:
        write("\033[2J\033[H" + content)
    else:
        write(content)


def _build_menu_frame(
    *,
    options: Sequence[str],
    selected: int,
    width: int,
    height: int,
    supports_ansi: bool,
) -> list[str]:
    safe_height = max(height, 12)
    lines = [""] * safe_height

    logo_lines = _normalized_logo_lines()

    logo_start = max(1, (safe_height // 3) - (len(logo_lines) // 2))
    for index, logo_line in enumerate(logo_lines):
        styled = logo_line
        if supports_ansi:
            styled = f"{_COLOR_PURPLE}{logo_line}{_COLOR_RESET}"
        _set_line(lines, logo_start + index, _center_text(styled, width))

    hint = "Use arrow keys and Enter"
    hint_line = max(logo_start + len(_ASCII_LOGO) + 1, safe_height - len(options) - 3)
    hint_text = _center_text(hint, width)
    if supports_ansi:
        hint_text = _center_text(f"{_COLOR_DIM}{hint}{_COLOR_RESET}", width)
    _set_line(lines, hint_line, hint_text)

    options_start = max(hint_line + 1, safe_height - len(options) - 1)
    for index, option in enumerate(options):
        marker = ">" if index == selected else " "
        label = f"{marker} {option}"
        if supports_ansi and index == selected:
            label = f"{_COLOR_BLUE}{label}{_COLOR_RESET}"
        elif supports_ansi:
            label = f"{_COLOR_PURPLE}{label}{_COLOR_RESET}"
        _set_line(lines, options_start + index, _center_text(label, width))

    return lines


def _set_line(lines: list[str], index: int, content: str) -> None:
    if 0 <= index < len(lines):
        lines[index] = content


def _center_text(text: str, width: int) -> str:
    plain_len = len(_strip_ansi(text))
    padding = max(0, (width - plain_len) // 2)
    return (" " * padding) + text


def _strip_ansi(text: str) -> str:
    output = []
    in_escape = False
    for char in text:
        if char == "\033":
            in_escape = True
            continue
        if in_escape and char == "m":
            in_escape = False
            continue
        if not in_escape:
            output.append(char)
    return "".join(output)


def _enable_ansi_if_supported() -> bool:
    if not sys.stdout.isatty():
        return False

    colorama_init()
    if not sys.platform.startswith("win"):
        return True

    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return False
        kernel32 = windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)) == 0:
            return False
        if kernel32.SetConsoleMode(handle, mode.value | 0x0004) == 0:
            return False
        return True
    except Exception:
        return False


def _normalized_logo_lines() -> tuple[str, ...]:
    max_width = max(len(line) for line in _ASCII_LOGO)
    return tuple(line.ljust(max_width) for line in _ASCII_LOGO)


def _hide_cursor(*, write: MenuWriter) -> None:
    write("\033[?25l")


def _show_cursor(*, write: MenuWriter) -> None:
    write("\033[?25h")


def run_settings_menu(env_path: Path) -> None:
    values = read_env_values(env_path)
    supports_ansi = _enable_ansi_if_supported()
    writer = _stdout_write

    while True:
        options = [
            _format_setting_option("Discord token", values.get("DISCORD_TOKEN", ""), secret=True),
            _format_setting_option("API key", values.get("API_KEY", ""), secret=True),
            _format_setting_option("Trigger prefix", values.get("TRIGGER_PREFIX", "eva ")),
            _format_setting_option(
                "Context messages",
                values.get("RESPONSE_CONTEXT_MESSAGES", "40"),
            ),
            _format_setting_option(
                "Search API key",
                values.get("SERPER_API_KEY", ""),
                secret=True,
            ),
            _format_setting_option(
                "Image API key",
                values.get("IMAGE_API_KEY", ""),
                secret=True,
            ),
            "Save and return",
            "Cancel",
        ]
        selected = run_menu(options=options, read_key=read_menu_key, write=writer)

        if selected == 6:
            write_env_values(env_path, _merge_env_values(values))
            return
        if selected == 7:
            return

        field_map = [
            "DISCORD_TOKEN",
            "API_KEY",
            "TRIGGER_PREFIX",
            "RESPONSE_CONTEXT_MESSAGES",
            "SERPER_API_KEY",
            "IMAGE_API_KEY",
        ]
        key = field_map[selected]
        current = values.get(key, _default_for_key(key))
        _show_cursor(write=writer)
        prompt = f"\n{key} [{current}]: "
        new_value = input(prompt).strip()
        if new_value:
            values[key] = new_value
        if supports_ansi:
            _hide_cursor(write=writer)


def _merge_env_values(updates: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for field in ENV_FIELDS:
        merged[field.key] = updates.get(field.key, field.default)
    return merged


def _default_for_key(key: str) -> str:
    for field in ENV_FIELDS:
        if field.key == key:
            return field.default
    return ""


def _format_setting_option(label: str, value: str, *, secret: bool = False) -> str:
    cleaned = value.strip()
    if secret and cleaned:
        display = "*" * min(len(cleaned), 8)
    elif cleaned:
        display = cleaned
    else:
        display = "(not set)"
    return f"{label}: {display}"


def run_live_dashboard(
    *,
    account: str,
    interaction_log_path: Path,
    on_minimize_to_tray: Callable[[], None],
    should_exit: Callable[[], bool],
) -> None:
    supports_ansi = _enable_ansi_if_supported()
    writer = _stdout_write

    while not should_exit():
        recent = tail_text_file(interaction_log_path, lines=8)
        account = _read_account_label(recent) or account
        lines = _build_dashboard_frame(
            account=account,
            interactions=_format_interaction_lines(recent),
            supports_ansi=supports_ansi,
        )
        _write_screen(frame=lines, write=writer, supports_ansi=supports_ansi)

        key = _poll_dashboard_key()
        if key == "minimize":
            on_minimize_to_tray()
        elif key == "quit":
            break
        time.sleep(0.15)

    _show_cursor(write=writer)


def _format_interaction_lines(lines: Sequence[str]) -> list[str]:
    output: list[str] = []
    for raw in lines:
        text = raw.strip()
        if "AI |" in text:
            output.append(text.split("AI |", 1)[1].strip())
        elif "ACCOUNT |" in text:
            continue
    return output[-6:]


def _read_account_label(lines: Sequence[str]) -> str | None:
    for raw in reversed(lines):
        if "ACCOUNT |" not in raw:
            continue
        marker = raw.split("ACCOUNT |", 1)[1].strip()
        return marker
    return None


def _build_dashboard_frame(
    *,
    account: str,
    interactions: Sequence[str],
    supports_ansi: bool,
) -> list[str]:
    width, height = shutil.get_terminal_size((100, 28))
    safe_height = max(height, 16)

    top = "+" + ("-" * (width - 2)) + "+"
    lines = [top]

    account_line = f" Account: {account}"
    lines.append("|" + account_line.ljust(width - 2)[: width - 2] + "|")
    lines.append("|" + (" Interactions".ljust(width - 2)) + "|")
    lines.append("|" + ("-" * (width - 2)) + "|")

    body_rows = max(4, safe_height - 8)
    for index in range(body_rows):
        text = interactions[-body_rows + index] if index >= body_rows - len(interactions) else ""
        line = f" AI | {text}" if text else ""
        lines.append("|" + line.ljust(width - 2)[: width - 2] + "|")

    lines.append("|" + ("-" * (width - 2)) + "|")
    footer = " [M] Send to tray  [Q] Quit dashboard "
    if supports_ansi:
        footer = (
            f" {_COLOR_BLUE}[M]{_COLOR_RESET} Send to tray  "
            f"{_COLOR_BLUE}[Q]{_COLOR_RESET} Quit dashboard "
        )
    lines.append("|" + footer.ljust(width - 2)[: width - 2] + "|")
    lines.append(top)
    return lines


def _poll_dashboard_key() -> str | None:
    if sys.platform.startswith("win"):
        return _poll_dashboard_key_windows()
    return None


def _poll_dashboard_key_windows() -> str | None:
    import msvcrt

    kbhit = getattr(msvcrt, "kbhit", None)
    getch = getattr(msvcrt, "getch", None)
    if kbhit is None or getch is None or not kbhit():
        return None

    key = getch().lower()
    if key == b"m":
        return "minimize"
    if key == b"q":
        return "quit"
    return None


def _stdout_write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


def _read_menu_key_windows() -> str:
    import msvcrt

    getch = getattr(msvcrt, "getch", None)
    if getch is None:
        return "enter"

    while True:
        key = getch()
        if key in {b"\x00", b"\xe0"}:
            special = getch()
            if special == b"H":
                return "up"
            if special == b"P":
                return "down"
            continue
        if key == b"\r":
            return "enter"
        if key == b"w":
            return "up"
        if key == b"s":
            return "down"


@contextmanager
def _raw_stdin() -> Iterator[None]:
    import termios
    import tty

    file_descriptor = sys.stdin.fileno()
    old_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        yield None
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, old_settings)


def _read_menu_key_posix() -> str:
    with _raw_stdin():
        while True:
            key = sys.stdin.read(1)
            if key == "\x1b":
                next_a = sys.stdin.read(1)
                next_b = sys.stdin.read(1)
                if next_a == "[" and next_b == "A":
                    return "up"
                if next_a == "[" and next_b == "B":
                    return "down"
                continue
            if key in {"\r", "\n"}:
                return "enter"
            if key == "w":
                return "up"
            if key == "s":
                return "down"
