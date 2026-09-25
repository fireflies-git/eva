from __future__ import annotations

import os
import subprocess  # nosec B404 - fixed internal CLI commands only.
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values, set_key

from eva.config import ACCOUNT_MODES, SETTINGS_DEFAULTS
from eva.runtime import get_resolved_env_path, validate_secure_path

_SETTING_DEFINITIONS = {
    "account-mode": {
        "env": "ACCOUNT_MODE",
        "default": SETTINGS_DEFAULTS["account_mode"],
        "description": "assistant or standalone",
        "choices": ACCOUNT_MODES,
    },
}


def _env_path() -> Path:
    return get_resolved_env_path()


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

    env_path = validate_secure_path(_env_path())
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{env_path.name}.tmp-",
        dir=env_path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            if env_path.exists():
                temp_file.write(env_path.read_text(encoding="utf-8"))
        if os.name != "nt":
            temp_path.chmod(0o600)
        set_key(str(temp_path), definition["env"], normalized_value)
        if os.name != "nt":
            temp_path.chmod(0o600)
        os.replace(temp_path, env_path)
        if os.name != "nt":
            env_path.chmod(0o600)
    finally:
        temp_path.unlink(missing_ok=True)
    print(f"Set {definition['env']}={normalized_value} in {env_path}")
    return 0


def run_tests() -> None:
    args = sys.argv[1:]
    command = ["pytest", "-q"]
    if args:
        command.extend(args)
    else:
        command.append("tests")
    raise SystemExit(subprocess.call(command))  # nosec B603 - fixed executable and args.


def run_lint() -> None:
    args = sys.argv[1:]
    command = ["ruff", "check"]
    if args:
        command.extend(args)
    else:
        command.extend(["src", "tests"])
    raise SystemExit(subprocess.call(command))  # nosec B603 - fixed executable and args.


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
    raise SystemExit(subprocess.call(command))  # nosec B603 - fixed executable and args.
