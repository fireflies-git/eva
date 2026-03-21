"""Application entrypoint."""

import argparse
import sys

from eva.app import EvaApp
from eva.config import ConfigError, get_env_path, get_runtime_base_dir, load_settings
from eva.logging import configure_logging, get_interaction_log_path
from eva.runtime import is_linux_service_mode, run_env_setup_wizard, show_interaction_logs
from eva.windows_tray import run_in_tray


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Eva runtime")
    parser.add_argument(
        "--setup-env",
        action="store_true",
        help="Run .env setup wizard",
    )
    parser.add_argument(
        "--show-logs",
        action="store_true",
        help="Show interaction logs and exit",
    )
    parser.add_argument(
        "--lines",
        type=int,
        default=80,
        help="Number of log lines to show with --show-logs",
    )
    parser.add_argument(
        "--tray",
        action="store_true",
        help="Run minimized to tray on Windows",
    )
    return parser.parse_args()


def _run_app() -> None:
    try:
        settings = load_settings()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    app = EvaApp(settings=settings)
    app.run()


def _show_menu() -> str:
    print("Eva CLI")
    print("1) Run Eva")
    print("2) Setup .env")
    print("3) Show interaction logs")
    if sys.platform.startswith("win"):
        print("4) Run minimized to tray")
        print("5) Exit")
        valid = {"1", "2", "3", "4", "5"}
    else:
        print("4) Exit")
        valid = {"1", "2", "3", "4"}

    while True:
        choice = input("Select an option: ").strip()
        if choice in valid:
            return choice
        print("Invalid choice. Try again.")


def _run_windows_tray() -> None:
    icon_path = get_runtime_base_dir() / "icon.ico"
    run_in_tray(run_app=_run_app, icon_path=icon_path)


def main() -> None:
    configure_logging()

    if is_linux_service_mode():
        env_path = get_env_path()
        if not env_path.exists():
            raise SystemExit(f"Error: missing {env_path}. Service mode requires a .env file.")
        _run_app()
        return

    args = _parse_args()
    env_path = get_env_path()

    if args.setup_env:
        run_env_setup_wizard(env_path)
        return

    if args.show_logs:
        show_interaction_logs(get_interaction_log_path(), lines=args.lines)
        return

    if args.tray:
        if not sys.platform.startswith("win"):
            raise SystemExit("Error: --tray is only supported on Windows")
        _run_windows_tray()
        return

    if not sys.argv[1:] and sys.stdin.isatty() and sys.stdout.isatty():
        selection = _show_menu()
        if selection == "1":
            _run_app()
            return
        if selection == "2":
            run_env_setup_wizard(env_path)
            return
        if selection == "3":
            show_interaction_logs(get_interaction_log_path(), lines=80)
            return
        if selection == "4" and sys.platform.startswith("win"):
            _run_windows_tray()
            return
        return

    _run_app()


if __name__ == "__main__":
    main()
