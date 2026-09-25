from __future__ import annotations

import pytest

from eva.tools import ToolAuthorizationError, ToolAuthorizer, ToolExecutionContext


def test_owner_admin_scope_allows_owner_and_admin() -> None:
    authorizer = ToolAuthorizer()
    assert authorizer.is_allowed(
        "run_terminal_command",
        ToolExecutionContext(requester_id=1, is_owner=True),
    )
    assert authorizer.is_allowed(
        "fetch_web_page",
        ToolExecutionContext(requester_id=2, is_admin=True),
    )


def test_owner_admin_scope_denies_whitelisted_user() -> None:
    authorizer = ToolAuthorizer()
    context = ToolExecutionContext(requester_id=3, is_whitelisted=True)

    assert not authorizer.is_allowed("run_terminal_command", context)
    with pytest.raises(ToolAuthorizationError):
        authorizer.authorize("run_terminal_command", context)


def test_missing_context_and_unknown_tools_fail_closed() -> None:
    authorizer = ToolAuthorizer()

    assert not authorizer.is_allowed("run_terminal_command", None)
    assert not authorizer.is_allowed(
        "future_tool",
        ToolExecutionContext(requester_id=1, is_owner=True),
    )


def test_scope_all_requires_a_real_requester() -> None:
    authorizer = ToolAuthorizer(scope="any")

    assert authorizer.is_allowed("run_terminal_command", ToolExecutionContext(requester_id=7))
    assert not authorizer.is_allowed(
        "run_terminal_command", ToolExecutionContext(requester_id=None)
    )


def test_invalid_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown autonomous tool scope"):
        ToolAuthorizer(scope="everyone")
