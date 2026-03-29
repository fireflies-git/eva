"""Application entrypoint."""

import argparse
import os
import sys
import threading
import time
from pathlib import Path

from eva.app import EvaApp
from eva.cli import run_settings
from eva.config import ConfigError, get_env_path, get_runtime_base_dir, load_settings
from eva.logging import configure_logging, get_interaction_log_path
from eva.runtime import (
    get_resolved_env_path,
    is_linux_service_mode,
    read_menu_key,
    run_live_dashboard,
    run_menu,
    run_settings_menu,
    show_interaction_logs,
)
from eva.windows_tray import run_in_tray, send_console_to_tray


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Eva runtime")
    parser.add_argument(
        "--setup-env",
        action="store_true",
        help="Open settings editor",
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
    options = ["Run Eva", "Settings", "Show interaction logs"]
    if sys.platform.startswith("win"):
        options.append("Run minimized to tray")
    options.append("Exit")
    selected = run_menu(options=options, read_key=read_menu_key)
    return options[selected]


def _run_windows_tray() -> None:
    icon_path = _resolve_icon_path()
    run_in_tray(run_app=_run_app, icon_path=icon_path)


def _resolve_icon_path() -> Path:
    runtime = get_runtime_base_dir() / "icon.ico"
    if runtime.exists():
        return runtime
    cwd = get_resolved_env_path().parent / "icon.ico"
    if cwd.exists():
        return cwd
    fallback = os.path.join(os.path.dirname(__file__), "..", "icon.ico")
    return Path(os.path.abspath(fallback))


def _run_with_dashboard() -> None:
    configure_logging(console_output=False)

    state = {
        "done": False,
        "error": None,
    }

    def app_worker() -> None:
        try:
            _run_app()
        except Exception as exc:
            state["error"] = str(exc)
        finally:
            state["done"] = True

    thread = threading.Thread(target=app_worker, name="eva-app", daemon=True)
    thread.start()

    def minimize_to_tray() -> None:
        if not sys.platform.startswith("win"):
            return
        send_console_to_tray(
            icon_path=_resolve_icon_path(),
            on_exit=lambda: os._exit(0),
        )

    run_live_dashboard(
        account="connecting...",
        interaction_log_path=get_interaction_log_path(),
        on_minimize_to_tray=minimize_to_tray,
        should_exit=lambda: bool(state["done"]),
    )

    while not state["done"]:
        time.sleep(0.1)

    if state["error"] is not None:
        raise SystemExit(str(state["error"]))


def _missing_service_mode_env_vars() -> list[str]:
    required_names = ("DISCORD_TOKEN", "API_KEY")
    return [name for name in required_names if not os.getenv(name, "").strip()]


def _ensure_service_mode_configuration(env_path: Path) -> None:
    if env_path.exists():
        return

    missing_vars = _missing_service_mode_env_vars()
    if not missing_vars:
        return

    missing_list = ", ".join(missing_vars)
    raise SystemExit(
        f"Error: missing {env_path}. Service mode requires a .env file or injected "
        f"environment variables for: {missing_list}."
    )


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "settings":
        raise SystemExit(run_settings(sys.argv[2:]))

    if is_linux_service_mode():
        configure_logging(console_output=True)
        env_path = get_env_path()
        _ensure_service_mode_configuration(env_path)
        _run_app()
        return

    args = _parse_args()
    env_path = get_env_path()

    if args.show_env_path:
        print(env_path)
        return

    if args.setup_env:
        run_settings_menu(env_path)
        return

    if args.show_logs:
        show_interaction_logs(get_interaction_log_path(), lines=args.lines)
        return

    if args.tray:
        configure_logging(console_output=False)
        if not sys.platform.startswith("win"):
            raise SystemExit("Error: --tray is only supported on Windows")
        _run_windows_tray()
        return

    if not sys.argv[1:] and sys.stdin.isatty() and sys.stdout.isatty():
        selection = _show_menu()
        if selection == "Run Eva":
            _run_with_dashboard()
            return
        if selection == "Settings":
            run_settings_menu(env_path)
            return
        if selection == "Show interaction logs":
            show_interaction_logs(get_interaction_log_path(), lines=80)
            return
        if selection == "Run minimized to tray" and sys.platform.startswith("win"):
            _run_windows_tray()
            return
        return

    configure_logging(console_output=True)
    _run_app()


if __name__ == "__main__":
    main()
