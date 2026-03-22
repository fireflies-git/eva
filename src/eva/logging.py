from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from eva.constants import INTERACTION_LOG_FILENAME


class ColorFormatter(logging.Formatter):
    COLORS: dict[int, str] = {
        logging.DEBUG: "\033[36m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def __init__(self, fmt: str, use_color: bool) -> None:
        super().__init__(fmt=fmt)
        self._use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        if not self._use_color:
            return super().format(record)

        color = self.COLORS.get(record.levelno)
        if color:
            original_levelname = record.levelname
            record.levelname = f"{color}{record.levelname}{self.RESET}"
            try:
                return super().format(record)
            finally:
                record.levelname = original_levelname
        return super().format(record)


def get_interaction_log_path() -> Path:
    raw = os.getenv("INTERACTION_LOG_PATH", "").strip()
    if raw:
        return Path(raw)
    return Path.cwd() / INTERACTION_LOG_FILENAME


def _build_interaction_file_handler() -> logging.Handler:
    log_path = get_interaction_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    return handler


def configure_logging(*, console_output: bool = True) -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    use_color = sys.stderr.isatty() and os.getenv("NO_COLOR") is None

    handlers: list[logging.Handler] = []
    if console_output:
        handler = logging.StreamHandler()
        handler.setFormatter(ColorFormatter(log_format, use_color=use_color))
        handlers.append(handler)

    interaction_logger = logging.getLogger("eva.interaction")
    interaction_logger.handlers = [_build_interaction_file_handler()]
    interaction_logger.setLevel(level)
    interaction_logger.propagate = False

    logging.basicConfig(
        level=level,
        handlers=handlers,
    )
