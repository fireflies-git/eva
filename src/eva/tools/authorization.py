from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

# Tool names are kept here instead of in request handling so the policy remains
# independent from the Discord trigger that happened to start a response.
DEFAULT_PROTECTED_TOOL_NAMES: Final[frozenset[str]] = frozenset(
    {
        "run_terminal_command",
        "fetch_web_page",
        "lookup_documentation",
    }
)


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    """Facts about the requester that are safe to use for tool authorization.

    The context is deliberately data-only.  It must be constructed by the
    Discord boundary, where user identity and trigger authorization are known;
    model supplied text must never be able to create or modify one.
    """

    requester_id: int | None
    is_owner: bool = False
    is_admin: bool = False
    is_whitelisted: bool = False
    account_mode: str = "assistant"
    channel_id: int | None = None
    trigger_type: str = "unknown"

    @property
    def is_privileged(self) -> bool:
        return self.requester_id is not None and (self.is_owner or self.is_admin)


class ToolAuthorizationError(PermissionError):
    """Raised when a requester is not allowed to use an autonomous tool."""


class ToolAuthorizer:
    """Authorize autonomous tools from trusted requester metadata.

    ``owner_admin`` is the secure default.  Broader scopes are explicit
    compatibility modes and should only be enabled in deployments that accept
    the additional risk.
    """

    VALID_SCOPES: Final[frozenset[str]] = frozenset(
        {"disabled", "owner_admin", "whitelisted", "any"}
    )

    def __init__(
        self,
        *,
        scope: str = "owner_admin",
        protected_tool_names: Collection[str] = DEFAULT_PROTECTED_TOOL_NAMES,
    ) -> None:
        normalized_scope = scope.strip().lower()
        if normalized_scope not in self.VALID_SCOPES:
            valid = ", ".join(sorted(self.VALID_SCOPES))
            raise ValueError(f"Unknown autonomous tool scope {scope!r}; expected one of {valid}")
        self._scope = normalized_scope
        self._protected_tool_names = frozenset(protected_tool_names)

    @property
    def scope(self) -> str:
        return self._scope

    def is_allowed(
        self,
        tool_name: str,
        context: ToolExecutionContext | None,
    ) -> bool:
        """Return whether *context* may invoke *tool_name*.

        Missing requester context always fails closed.  ``tool_name`` is still
        checked against the protected set so a future caller cannot accidentally
        use this policy as an allow-all gate for unrelated internal tools.
        """

        if context is None or context.requester_id is None:
            return False
        if tool_name not in self._protected_tool_names:
            return False
        if self._scope == "disabled":
            return False
        if self._scope == "owner_admin":
            return context.is_privileged
        if self._scope == "whitelisted":
            return context.is_whitelisted or context.is_privileged
        # ``any`` still requires a real requester ID, preventing anonymous
        # background work from gaining a user-facing tool capability.
        return True

    def authorize(
        self,
        tool_name: str,
        context: ToolExecutionContext | None,
    ) -> None:
        if self.is_allowed(tool_name, context):
            return
        raise ToolAuthorizationError(f"Requester is not authorized to use tool {tool_name!r}.")

    def filter_tool_services(
        self,
        services: tuple[object, ...] | list[object],
        context: ToolExecutionContext | None,
    ) -> list[object]:
        """Return services whose tool names are authorized for this context."""

        authorized: list[object] = []
        for service in services:
            name = getattr(service, "autonomous_tool_name", None)
            if isinstance(name, str) and self.is_allowed(name, context):
                authorized.append(service)
        return authorized
