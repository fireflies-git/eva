from __future__ import annotations

from pathlib import Path

import pytest

import main as main_module


def test_main_allows_service_mode_with_injected_env_vars(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    called = {"run_app": False}

    monkeypatch.setattr(main_module.sys, "argv", ["eva"])
    monkeypatch.setattr(main_module, "is_linux_service_mode", lambda: True)
    monkeypatch.setattr(main_module, "configure_logging", lambda *, console_output: None)
    monkeypatch.setattr(main_module, "get_env_path", lambda: env_path)
    monkeypatch.setattr(
        main_module,
        "_run_app",
        lambda: called.__setitem__("run_app", True),
    )
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("API_KEY", "key")

    main_module.main()

    assert called["run_app"] is True


def test_main_rejects_unconfigured_service_mode(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"

    monkeypatch.setattr(main_module.sys, "argv", ["eva"])
    monkeypatch.setattr(main_module, "is_linux_service_mode", lambda: True)
    monkeypatch.setattr(main_module, "configure_logging", lambda *, console_output: None)
    monkeypatch.setattr(main_module, "get_env_path", lambda: env_path)
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.delenv("API_KEY", raising=False)

    with pytest.raises(SystemExit, match="DISCORD_TOKEN, API_KEY"):
        main_module.main()
