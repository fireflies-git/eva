from __future__ import annotations

import subprocess
import sys


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
        "nuitka",
        "--standalone",
        "--onefile",
        "--assume-yes-for-downloads",
        "--output-filename=eva",
    ]
    if args:
        command.extend(args)

    command.append("src/main.py")
    raise SystemExit(subprocess.call(command))

