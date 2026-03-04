from __future__ import annotations

import logging
import os
import sys


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


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_format = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    use_color = sys.stderr.isatty() and os.getenv("NO_COLOR") is None

    handler = logging.StreamHandler()
    handler.setFormatter(ColorFormatter(log_format, use_color=use_color))

    logging.basicConfig(
        level=level,
        handlers=[handler],
    )
