from __future__ import annotations

import logging
import os
import re
import stat
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from eva.constants import INTERACTION_LOG_FILENAME
from eva.runtime import validate_secure_path


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
            return redact_secrets(super().format(record))

        color = self.COLORS.get(record.levelno)
        if color:
            original_levelname = record.levelname
            record.levelname = f"{color}{record.levelname}{self.RESET}"
            try:
                return redact_secrets(super().format(record))
            finally:
                record.levelname = original_levelname
        return redact_secrets(super().format(record))


_AUTH_HEADER_RE = re.compile(
    r"(?ix)(?P<prefix>['\"]?authorization['\"]?\s*[:=]\s*)"
    r"(?P<container_quote>['\"]?)bearer\s+"
    r"(?P<token_quote>['\"]?)(?P<value>[^\s,;\"']+)"
    r"(?P=token_quote)(?P=container_quote)"
)
_SECRET_FIELD_RE = re.compile(
    r"(?ix)(?P<prefix>['\"]?"
    r"(?:api[_-]?key|access[_-]?token|refresh[_-]?token|discord[_-]?token|"
    r"token|password|secret|cookie)['\"]?\s*[:=]\s*)"
    r"(?P<quote>['\"]?)(?P<value>[^\s,;\"']+)(?P=quote)"
)
_SECRET_QUERY_RE = re.compile(
    r"(?ix)(?P<prefix>[?&](?:api[_-]?key|access[_-]?token|refresh[_-]?token|token)=)"
    r"(?P<value>[^&#\s]+)"
)
_ENV_PATH_RE = re.compile(
    r"(?ix)(?P<lead>^|[\s'\"=])(?P<path>"
    r"(?:[a-z]:)?[^\s,;\"']*[\\/]\.env(?:[^\s,;\"']*)?)"
)


def redact_secrets(value: str) -> str:
    redacted = _AUTH_HEADER_RE.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('container_quote')}Bearer "
            f"{match.group('token_quote')}[REDACTED]"
            f"{match.group('token_quote')}{match.group('container_quote')}"
        ),
        value,
    )
    redacted = _SECRET_FIELD_RE.sub(
        lambda match: (
            f"{match.group('prefix')}{match.group('quote')}[REDACTED]"
            f"{match.group('quote')}"
        ),
        redacted,
    )
    redacted = _SECRET_QUERY_RE.sub(
        lambda match: f"{match.group('prefix')}[REDACTED]",
        redacted,
    )
    return _ENV_PATH_RE.sub(
        lambda match: f"{match.group('lead')}[REDACTED_ENV_PATH]",
        redacted,
    )


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


def get_interaction_log_path() -> Path:
    raw = os.getenv("INTERACTION_LOG_PATH", "").strip()
    if raw:
        return validate_secure_path(Path(raw))
    return validate_secure_path(Path.cwd() / INTERACTION_LOG_FILENAME)


def _build_interaction_file_handler() -> logging.Handler:
    log_path = get_interaction_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    if os.name != "nt":
        try:
            log_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    handler.setFormatter(
        RedactingFormatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
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
    for handler in interaction_logger.handlers:
        handler.close()
    interaction_logger.handlers = []
    interaction_logging_enabled = os.getenv("INTERACTION_LOG_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if interaction_logging_enabled:
        interaction_logger.addHandler(_build_interaction_file_handler())
    interaction_logger.setLevel(level)
    interaction_logger.propagate = False

    logging.basicConfig(
        level=level,
        handlers=handlers,
    )
