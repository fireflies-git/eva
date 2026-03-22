"""Application entrypoint."""

import argparse
import sys

from eva.app import EvaApp
from eva.config import ConfigError, get_env_path, get_runtime_base_dir, load_settings
from eva.logging import configure_logging, get_interaction_log_path
from eva.runtime import (
    is_linux_service_mode,
    read_menu_key,
    run_env_setup_wizard,
    run_menu,
    show_interaction_logs,
)
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
    parser.add_argument(
        "--show-env-path",
        action="store_true",
        help="Print resolved .env path and exit",
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
    options = ["Run Eva", "Setup .env", "Show interaction logs"]
    if sys.platform.startswith("win"):
        options.append("Run minimized to tray")
    options.append("Exit")
    selected = run_menu(options=options, read_key=read_menu_key)
    return options[selected]


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

    if args.show_env_path:
        print(env_path)
        return

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
        if selection == "Run Eva":
            _run_app()
            return
        if selection == "Setup .env":
            run_env_setup_wizard(env_path)
            return
        if selection == "Show interaction logs":
            show_interaction_logs(get_interaction_log_path(), lines=80)
            return
        if selection == "Run minimized to tray" and sys.platform.startswith("win"):
            _run_windows_tray()
            return
        return

    _run_app()


if __name__ == "__main__":
    main()
