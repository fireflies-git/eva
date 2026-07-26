"""Autonomous tool services for Eva."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = [
    "Context7Service",
    "PlaywrightService",
    "ToolService",
]


@runtime_checkable
class ToolService(Protocol):
    """Interface each autonomous tool service must satisfy.

    Follows the same contract as ``TerminalService`` so existing
    terminal integration conforms without any code changes.
    """

    @property
    def autonomous_tool_name(self) -> str: ...

    def build_autonomous_tool_definition(self) -> dict[str, object]: ...

    async def run_autonomous_tool(self, arguments: str) -> str: ...


from eva.tools.context7_service import Context7Service  # noqa: E402
from eva.tools.playwright_service import PlaywrightService  # noqa: E402
