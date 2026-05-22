from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from eva.constants import (
    DEFAULT_MAX_HISTORY_MESSAGES,
    DEFAULT_RESPONSE_CONTEXT_MESSAGES,
    X_MARK,
)
from eva.runtime import get_env_search_paths, get_resolved_env_path

SETTINGS_DEFAULTS = {
    "api_base_url": "https://inference.do-ai.run/v1",
    "account_mode": "assistant",
    "model_name": "openai-gpt-oss-120b",
    "split_model_name": "llama3.3-70b-instruct",
    "trigger_prefix": "eva ",
    "max_history_messages": DEFAULT_MAX_HISTORY_MESSAGES,
    "response_context_messages": DEFAULT_RESPONSE_CONTEXT_MESSAGES,
    "request_timeout_seconds": 30.0,
    "min_loading_seconds": 1.0,
    "followup_delay_min_seconds": 0.75,
    "followup_delay_max_seconds": 1.5,
    # Image generation
    "image_api_base_url": "https://ai.6969.pro/v1",
    "image_model_name": "sonar",
    "image_language": "en-US",
    "image_incognito": True,
    "terminal_enabled": True,
    "terminal_autonomous_enabled": True,
    "terminal_workdir": "/app",
    "terminal_shell": "/bin/sh",
    "terminal_timeout_seconds": 15.0,
    "terminal_max_output_chars": 6000,
    "rate_limit_max_requests": 20,
    "rate_limit_window_seconds": 60.0,
}
RESPONSE_CONTEXT_MESSAGES_MIN = 1
RESPONSE_CONTEXT_MESSAGES_MAX = 100
FOLLOWUP_DELAY_SECONDS_MIN = 0.0
FOLLOWUP_DELAY_SECONDS_MAX = 10.0
TERMINAL_TIMEOUT_SECONDS_MIN = 1.0
TERMINAL_TIMEOUT_SECONDS_MAX = 120.0
TERMINAL_MAX_OUTPUT_CHARS_MIN = 200
TERMINAL_MAX_OUTPUT_CHARS_MAX = 20000
RATE_LIMIT_MAX_REQUESTS_MIN = 1
RATE_LIMIT_MAX_REQUESTS_MAX = 10000
RATE_LIMIT_WINDOW_SECONDS_MIN = 1.0
RATE_LIMIT_WINDOW_SECONDS_MAX = 3600.0
ACCOUNT_MODES = {"assistant", "standalone"}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    api_key: str
    serper_api_key: str | None
    image_api_key: str | None
    api_base_url: str
    account_mode: str
    model_name: str
    split_model_name: str
    trigger_prefix: str
    max_history_messages: int
    response_context_messages: int
    request_timeout_seconds: float
    min_loading_seconds: float
    followup_delay_min_seconds: float
    followup_delay_max_seconds: float

    image_api_base_url: str
    image_model_name: str
    image_language: str
    image_incognito: bool
    terminal_enabled: bool
    terminal_autonomous_enabled: bool
    terminal_workdir: str
    terminal_shell: str
    terminal_timeout_seconds: float
    terminal_max_output_chars: int
    rate_limit_max_requests: int
    rate_limit_window_seconds: float


def get_runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.argv[0]).resolve().parent
    return Path.cwd()


def get_env_path() -> Path:
    return get_resolved_env_path()


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigError(f"{X_MARK} Missing required environment variable: {name}")
    return value


def _optional_env(name: str, *, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _optional_secret(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _optional_bool(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean, got {raw!r}")


def _optional_int(name: str, *, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def _optional_float(name: str, *, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if value < minimum or value > maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


def _optional_choice(name: str, *, default: str, choices: set[str]) -> str:
    value = _optional_env(name, default=default).lower()
    if value not in choices:
        allowed = ", ".join(sorted(choices))
        raise ConfigError(f"{name} must be one of: {allowed}. Got {value!r}")
    return value


def load_settings() -> Settings:
    env_path = get_env_path()
    load_dotenv(dotenv_path=env_path)

    followup_delay_min_seconds = _optional_float(
        "FOLLOWUP_DELAY_MIN_SECONDS",
        default=SETTINGS_DEFAULTS["followup_delay_min_seconds"],
        minimum=FOLLOWUP_DELAY_SECONDS_MIN,
        maximum=FOLLOWUP_DELAY_SECONDS_MAX,
    )
    followup_delay_max_seconds = _optional_float(
        "FOLLOWUP_DELAY_MAX_SECONDS",
        default=max(
            SETTINGS_DEFAULTS["followup_delay_max_seconds"],
            followup_delay_min_seconds,
        ),
        minimum=followup_delay_min_seconds,
        maximum=FOLLOWUP_DELAY_SECONDS_MAX,
    )

    try:
        return Settings(
            discord_token=_required_env("DISCORD_TOKEN"),
            api_key=_required_env("API_KEY"),
            serper_api_key=_optional_secret("SERPER_API_KEY"),
            image_api_key=_optional_secret("IMAGE_API_KEY"),
            api_base_url=_optional_env("API_BASE_URL", default=SETTINGS_DEFAULTS["api_base_url"]),
            account_mode=_optional_choice(
                "ACCOUNT_MODE",
                default=SETTINGS_DEFAULTS["account_mode"],
                choices=ACCOUNT_MODES,
            ),
            model_name=_optional_env("MODEL_NAME", default=SETTINGS_DEFAULTS["model_name"]),
            split_model_name=_optional_env(
                "SPLIT_MODEL_NAME",
                default=SETTINGS_DEFAULTS["split_model_name"],
            ),
            trigger_prefix=_optional_env(
                "TRIGGER_PREFIX",
                default=SETTINGS_DEFAULTS["trigger_prefix"],
            ),
            max_history_messages=SETTINGS_DEFAULTS["max_history_messages"],
            response_context_messages=_optional_int(
                "RESPONSE_CONTEXT_MESSAGES",
                default=SETTINGS_DEFAULTS["response_context_messages"],
                minimum=RESPONSE_CONTEXT_MESSAGES_MIN,
                maximum=RESPONSE_CONTEXT_MESSAGES_MAX,
            ),
            request_timeout_seconds=SETTINGS_DEFAULTS["request_timeout_seconds"],
            min_loading_seconds=SETTINGS_DEFAULTS["min_loading_seconds"],
            followup_delay_min_seconds=followup_delay_min_seconds,
            followup_delay_max_seconds=followup_delay_max_seconds,
            image_api_base_url=_optional_env(
                "IMAGE_API_BASE_URL",
                default=SETTINGS_DEFAULTS["image_api_base_url"],
            ),
            image_model_name=_optional_env(
                "IMAGE_MODEL_NAME",
                default=SETTINGS_DEFAULTS["image_model_name"],
            ),
            image_language=_optional_env(
                "IMAGE_LANGUAGE",
                default=SETTINGS_DEFAULTS["image_language"],
            ),
            image_incognito=_optional_bool(
                "IMAGE_INCOGNITO",
                default=SETTINGS_DEFAULTS["image_incognito"],
            ),
            terminal_enabled=_optional_bool(
                "TERMINAL_ENABLED",
                default=SETTINGS_DEFAULTS["terminal_enabled"],
            ),
            terminal_autonomous_enabled=_optional_bool(
                "TERMINAL_AUTONOMOUS_ENABLED",
                default=SETTINGS_DEFAULTS["terminal_autonomous_enabled"],
            ),
            terminal_workdir=_optional_env(
                "TERMINAL_WORKDIR",
                default=SETTINGS_DEFAULTS["terminal_workdir"],
            ),
            terminal_shell=_optional_env(
                "TERMINAL_SHELL",
                default=SETTINGS_DEFAULTS["terminal_shell"],
            ),
            terminal_timeout_seconds=_optional_float(
                "TERMINAL_TIMEOUT_SECONDS",
                default=SETTINGS_DEFAULTS["terminal_timeout_seconds"],
                minimum=TERMINAL_TIMEOUT_SECONDS_MIN,
                maximum=TERMINAL_TIMEOUT_SECONDS_MAX,
            ),
            terminal_max_output_chars=_optional_int(
                "TERMINAL_MAX_OUTPUT_CHARS",
                default=SETTINGS_DEFAULTS["terminal_max_output_chars"],
                minimum=TERMINAL_MAX_OUTPUT_CHARS_MIN,
                maximum=TERMINAL_MAX_OUTPUT_CHARS_MAX,
            ),
            rate_limit_max_requests=_optional_int(
                "RATE_LIMIT_MAX_REQUESTS",
                default=SETTINGS_DEFAULTS["rate_limit_max_requests"],
                minimum=RATE_LIMIT_MAX_REQUESTS_MIN,
                maximum=RATE_LIMIT_MAX_REQUESTS_MAX,
            ),
            rate_limit_window_seconds=_optional_float(
                "RATE_LIMIT_WINDOW_SECONDS",
                default=SETTINGS_DEFAULTS["rate_limit_window_seconds"],
                minimum=RATE_LIMIT_WINDOW_SECONDS_MIN,
                maximum=RATE_LIMIT_WINDOW_SECONDS_MAX,
            ),
        )
    except ConfigError as exc:
        candidates = ", ".join(str(path) for path in get_env_search_paths())
        raise ConfigError(f"{exc} (env paths checked: {candidates})") from exc
