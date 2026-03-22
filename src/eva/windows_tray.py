from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class TrayIcon(Protocol):
    def stop(self) -> None: ...


def run_in_tray(*, run_app: Callable[[], None], icon_path: Path) -> None:
    try:
        import pystray  # pyright: ignore[reportMissingImports]
        from PIL import Image  # pyright: ignore[reportMissingImports]
    except Exception as exc:
        raise RuntimeError("Windows tray mode requires pystray and Pillow dependencies") from exc

    image = _load_icon(Image, icon_path)
    stop_event = threading.Event()

    def app_worker() -> None:
        try:
            run_app()
        except Exception:
            logger.exception("Eva app terminated unexpectedly in tray mode")
        finally:
            stop_event.set()

    def setup(icon: TrayIcon) -> None:
        threading.Thread(target=app_worker, name="eva-app", daemon=True).start()

        def monitor() -> None:
            stop_event.wait()
            try:
                icon.stop()
            except Exception:
                logger.exception("Failed to stop tray icon")

        threading.Thread(target=monitor, name="eva-tray-monitor", daemon=True).start()

    def on_exit(icon: TrayIcon, item: object) -> None:
        stop_event.set()
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(pystray.MenuItem("Exit Eva", on_exit))
    icon = pystray.Icon("eva", image, "Eva", menu)
    icon.run(setup=setup)


def send_console_to_tray(
    *,
    icon_path: Path,
    on_exit: Callable[[], None],
) -> None:
    try:
        import pystray  # pyright: ignore[reportMissingImports]
        from PIL import Image  # pyright: ignore[reportMissingImports]
    except Exception as exc:
        raise RuntimeError("Windows tray mode requires pystray and Pillow dependencies") from exc

    image = _load_icon(Image, icon_path)
    _hide_console_window()

    should_exit = {"value": False}

    def on_show(icon: TrayIcon, item: object) -> None:
        _show_console_window()
        icon.stop()

    def on_exit_click(icon: TrayIcon, item: object) -> None:
        should_exit["value"] = True
        _show_console_window()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Show Eva", on_show),
        pystray.MenuItem("Exit Eva", on_exit_click),
    )
    icon = pystray.Icon("eva", image, "Eva", menu)
    icon.run()

    if should_exit["value"]:
        on_exit()


def _load_icon(image_module: Any, icon_path: Path) -> Any:
    if icon_path.exists():
        return image_module.open(icon_path).convert("RGBA")
    return image_module.new("RGBA", (16, 16), color=(70, 105, 180, 255))


def _hide_console_window() -> None:
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return
        hwnd = windll.kernel32.GetConsoleWindow()
        if hwnd:
            windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        logger.exception("Failed to hide console window")


def _show_console_window() -> None:
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)
        if windll is None:
            return
        hwnd = windll.kernel32.GetConsoleWindow()
        if hwnd:
            windll.user32.ShowWindow(hwnd, 9)
            windll.user32.SetForegroundWindow(hwnd)
    except Exception:
        logger.exception("Failed to show console window")
