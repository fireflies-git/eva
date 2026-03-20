from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from dotenv import load_dotenv

from eva.constants import (
    DEFAULT_MAX_HISTORY_MESSAGES,
    DEFAULT_RESPONSE_CONTEXT_MESSAGES,
    X_MARK,
)

SETTINGS_DEFAULTS = {
    "api_base_url": "https://inference.do-ai.run/v1",
    "model_name": "openai-gpt-oss-120b",
    "trigger_prefix": "eva ",
    "max_history_messages": DEFAULT_MAX_HISTORY_MESSAGES,
    "response_context_messages": DEFAULT_RESPONSE_CONTEXT_MESSAGES,
    "request_timeout_seconds": 30.0,
    "min_loading_seconds": 1.0,
}
RESPONSE_CONTEXT_MESSAGES_MIN = 1
RESPONSE_CONTEXT_MESSAGES_MAX = 100

class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    discord_token: str
    api_key: str
    serper_api_key: str | None
    api_base_url: str
    model_name: str
    trigger_prefix: str
    max_history_messages: int
    response_context_messages: int
    request_timeout_seconds: float
    min_loading_seconds: float


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


def load_settings() -> Settings:
    # When compiled with Nuitka/PyInstaller, the executable runs in a tmp dir,
    # so we must explicitly load .env from the directory of the executable
    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        env_path = os.path.join(base_dir, ".env")
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()

    return Settings(
        discord_token=_required_env("DISCORD_TOKEN"),
        api_key=_required_env("API_KEY"),
        serper_api_key=_optional_secret("SERPER_API_KEY"),
        api_base_url=_optional_env("API_BASE_URL", default=SETTINGS_DEFAULTS["api_base_url"]),
        model_name=_optional_env("MODEL_NAME", default=SETTINGS_DEFAULTS["model_name"]),
        trigger_prefix=_optional_env("TRIGGER_PREFIX", default=SETTINGS_DEFAULTS["trigger_prefix"]),
        max_history_messages=SETTINGS_DEFAULTS["max_history_messages"],
        response_context_messages=_optional_int(
            "RESPONSE_CONTEXT_MESSAGES",
            default=SETTINGS_DEFAULTS["response_context_messages"],
            minimum=RESPONSE_CONTEXT_MESSAGES_MIN,
            maximum=RESPONSE_CONTEXT_MESSAGES_MAX,
        ),
        request_timeout_seconds=SETTINGS_DEFAULTS["request_timeout_seconds"],
        min_loading_seconds=SETTINGS_DEFAULTS["min_loading_seconds"],
    )
