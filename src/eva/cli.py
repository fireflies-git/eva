from __future__ import annotations

import asyncio
import base64
import os
import subprocess  # nosec B404 - fixed internal CLI commands only.
import sys
import tempfile
from pathlib import Path

from dotenv import dotenv_values, set_key

from eva.ai.client import AIClientError, OpenAICompatibleClient
from eva.ai.schemas import ChatMessage
from eva.config import ACCOUNT_MODES, SETTINGS_DEFAULTS
from eva.runtime import get_resolved_env_path, validate_secure_path

_SETTING_DEFINITIONS = {
    "account-mode": {
        "env": "ACCOUNT_MODE",
        "default": SETTINGS_DEFAULTS["account_mode"],
        "description": "assistant or standalone",
        "choices": ACCOUNT_MODES,
    },
}


def _env_path() -> Path:
    return get_resolved_env_path()


def _print_settings_usage() -> None:
    print("Usage:")
    print("  eva settings show")
    print("  eva settings set account-mode <assistant|standalone>")


def run_settings(args: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if args is None else args)
    if not arguments or arguments[0] == "show":
        return _show_settings()
    if arguments[0] == "set":
        if len(arguments) != 3:
            _print_settings_usage()
            return 2
        return _set_setting(arguments[1], arguments[2])

    _print_settings_usage()
    return 2


def _show_settings() -> int:
    env_values = dotenv_values(_env_path())
    print("Eva CLI settings")
    for key, definition in _SETTING_DEFINITIONS.items():
        env_name = definition["env"]
        current_value = env_values.get(env_name) or definition["default"]
        description = definition["description"]
        print(f"- {key}: {current_value} ({description})")
    return 0


def _set_setting(key: str, value: str) -> int:
    normalized_key = key.strip().lower()
    definition = _SETTING_DEFINITIONS.get(normalized_key)
    if definition is None:
        print(f"Unknown setting: {key}", file=sys.stderr)
        _print_settings_usage()
        return 2

    normalized_value = value.strip().lower()
    choices = definition.get("choices")
    if isinstance(choices, set) and normalized_value not in choices:
        allowed = ", ".join(sorted(choices))
        print(f"Invalid value for {key}: {value}. Allowed: {allowed}", file=sys.stderr)
        return 2

    env_path = validate_secure_path(_env_path())
    env_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{env_path.name}.tmp-",
        dir=env_path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
            if env_path.exists():
                temp_file.write(env_path.read_text(encoding="utf-8"))
        if os.name != "nt":
            temp_path.chmod(0o600)
        set_key(str(temp_path), definition["env"], normalized_value)
        if os.name != "nt":
            temp_path.chmod(0o600)
        os.replace(temp_path, env_path)
        if os.name != "nt":
            env_path.chmod(0o600)
    finally:
        temp_path.unlink(missing_ok=True)
    print(f"Set {definition['env']}={normalized_value} in {env_path}")
    return 0


def run_tests() -> None:
    args = sys.argv[1:]
    command = ["pytest", "-q"]
    if args:
        command.extend(args)
    else:
        command.append("tests")
    raise SystemExit(subprocess.call(command))  # nosec B603 - fixed executable and args.


def run_lint() -> None:
    args = sys.argv[1:]
    command = ["ruff", "check"]
    if args:
        command.extend(args)
    else:
        command.extend(["src", "tests"])
    raise SystemExit(subprocess.call(command))  # nosec B603 - fixed executable and args.


def run_build() -> None:
    args = sys.argv[1:]
    command = [
        sys.executable,
        "-m",
        "nuitka",
        "--standalone",
        "--onefile",
        "--assume-yes-for-downloads",
        "--output-filename=eva",
    ]
    if sys.platform.startswith("win"):
        command.extend(
            [
                "--windows-icon-from-ico=icon.ico",
                "--include-data-files=icon.ico=icon.ico",
            ]
        )
    if args:
        command.extend(args)

    command.append("src/main.py")
    raise SystemExit(subprocess.call(command))  # nosec B603 - fixed executable and args.


def run_model_check(video_url: str | None = None) -> int:
    """Probe the configured provider without starting Discord."""
    from eva.config import ConfigError, load_settings
    from eva.security.urls import URLPolicyError, validate_url

    try:
        settings = load_settings()
        if video_url:
            validate_url(video_url, allow_private=settings.allow_private_outbound)
        return asyncio.run(_model_check_async(settings, video_url=video_url))
    except (ConfigError, AIClientError, URLPolicyError, OSError) as exc:
        print(f"model-check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


async def _model_check_async(settings: object, *, video_url: str | None) -> int:
    client = OpenAICompatibleClient(
        api_key=settings.api_key,  # type: ignore[attr-defined]
        base_url=settings.api_base_url,  # type: ignore[attr-defined]
        default_model=settings.model_name,  # type: ignore[attr-defined]
        timeout_seconds=settings.request_timeout_seconds,  # type: ignore[attr-defined]
        reasoning_effort=settings.reasoning_effort,  # type: ignore[attr-defined]
        clear_thinking=settings.clear_thinking,  # type: ignore[attr-defined]
        allow_private_outbound=settings.allow_private_outbound,  # type: ignore[attr-defined]
        allowed_hosts=settings.outbound_allowed_hosts or None,  # type: ignore[attr-defined]
    )
    try:
        try:
            models = await client.list_models()
            if models and not any(
                isinstance(model, dict) and model.get("id") == settings.model_name  # type: ignore[attr-defined]
                for model in models
            ):
                print(f"warning: {settings.model_name!r} was not listed by /models")  # type: ignore[attr-defined]
        except AIClientError as exc:
            print(f"warning: /models unavailable ({exc})", file=sys.stderr)

        text = await client.chat_completion(
            messages=[{"role": "user", "content": "Reply with the word ready."}],
            model=settings.model_name,  # type: ignore[attr-defined]
            max_tokens=64,
        )
        if not text.strip():
            raise AIClientError("text probe returned empty visible content")

        tool_output = await client.chat_completion_with_tools(
            messages=[
                {
                    "role": "user",
                    "content": "Call the probe tool with {\"ok\":true}; do not answer with text.",
                }
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "probe",
                        "description": "Provider compatibility probe",
                        "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}},
                    },
                }
            ],
            model=settings.model_name,  # type: ignore[attr-defined]
            max_tokens=256,
        )
        if not tool_output.tool_calls:
            raise AIClientError("tool probe returned no tool call")
        if tool_output.finish_reason not in {"tool_calls", None}:
            raise AIClientError(f"unexpected tool finish reason: {tool_output.finish_reason}")

        png = base64.b64encode(
            bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000a49444154789c6360000000020001e221bc330000000049454e44ae426082")
        ).decode("ascii")
        media_messages: list[ChatMessage] = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe the attached inputs in one word."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png}"}},
                    {
                        "type": "file",
                        "file": {
                            "file_data": "data:text/plain;base64,SGVsbG8=",
                            "filename": "probe.txt",
                        },
                    },
                ],
            }
        ]
        if video_url:
            content = media_messages[0]["content"]
            if isinstance(content, list):
                content.append({"type": "video_url", "video_url": {"url": video_url}})
        media_text = await client.chat_completion(
            messages=media_messages,
            model=settings.model_name,  # type: ignore[attr-defined]
            max_tokens=64,
        )
        if not media_text.strip():
            raise AIClientError("multimodal probe returned empty visible content")
    finally:
        await client.close()
    print(f"model-check passed for {settings.model_name}")  # type: ignore[attr-defined]
    return 0
