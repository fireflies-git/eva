from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key

from eva.config import ACCOUNT_MODES, SETTINGS_DEFAULTS

_SETTING_DEFINITIONS = {
    "account-mode": {
        "env": "ACCOUNT_MODE",
        "default": SETTINGS_DEFAULTS["account_mode"],
        "description": "assistant or standalone",
        "choices": ACCOUNT_MODES,
    },
}


def _env_path() -> Path:
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        return Path(sys.argv[0]).resolve().parent / ".env"
    return Path(".env")


def _print_settings_usage() -> None:
    print("Usage:")
    print("  eva settings show")
    print("  eva settings set account-mode <assistant|standalone>")


def run_settings(args: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if args is None else args)
    if not arguments or arguments[0] == "show":
        return _show_settings()
    if arguments[0] == "set":
        if len(arguments) != 3:
            _print_settings_usage()
            return 2
        return _set_setting(arguments[1], arguments[2])

    _print_settings_usage()
    return 2


def _show_settings() -> int:
    env_values = dotenv_values(_env_path())
    print("Eva CLI settings")
    for key, definition in _SETTING_DEFINITIONS.items():
        env_name = definition["env"]
        current_value = env_values.get(env_name) or definition["default"]
        description = definition["description"]
        print(f"- {key}: {current_value} ({description})")
    return 0


def _set_setting(key: str, value: str) -> int:
    normalized_key = key.strip().lower()
    definition = _SETTING_DEFINITIONS.get(normalized_key)
    if definition is None:
        print(f"Unknown setting: {key}", file=sys.stderr)
        _print_settings_usage()
        return 2

    normalized_value = value.strip().lower()
    choices = definition.get("choices")
    if isinstance(choices, set) and normalized_value not in choices:
        allowed = ", ".join(sorted(choices))
        print(f"Invalid value for {key}: {value}. Allowed: {allowed}", file=sys.stderr)
        return 2

    env_path = _env_path()
    if not env_path.exists():
        env_path.touch()
    set_key(str(env_path), definition["env"], normalized_value)
    print(f"Set {definition['env']}={normalized_value} in {env_path}")
    return 0


def run_tests() -> None:
    args = sys.argv[1:]
    command = ["pytest", "-q"]
    if args:
        command.extend(args)
    else:
        command.append("tests")
    raise SystemExit(subprocess.call(command))


def run_lint() -> None:
    args = sys.argv[1:]
    command = ["ruff", "check"]
    if args:
        command.extend(args)
    else:
        command.extend(["src", "tests"])
    raise SystemExit(subprocess.call(command))


def run_build() -> None:
    args = sys.argv[1:]
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--onefile",
        "--assume-yes-for-downloads",
        "--output-filename=eva",
    ]
    if sys.platform.startswith("win"):
        command.extend(
            [
                "--windows-icon-from-ico=icon.ico",
                "--include-data-files=icon.ico=icon.ico",
            ]
        )
    if args:
        command.extend(args)

    command.append("src/main.py")
    raise SystemExit(subprocess.call(command))
