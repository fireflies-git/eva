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


def _load_icon(image_module: Any, icon_path: Path) -> Any:
    if icon_path.exists():
        return image_module.open(icon_path)
    return image_module.new("RGBA", (16, 16), color=(70, 105, 180, 255))
