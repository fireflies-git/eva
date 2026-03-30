from __future__ import annotations

from dataclasses import dataclass

from eva.constants import CHECK_MARK, X_MARK
from eva.discord.commands import is_admin_user
from eva.terminal import TerminalClientError, TerminalService, format_terminal_result

_TERMINAL_COMMANDS = ("shell", "exec")


@dataclass(frozen=True, slots=True)
class TerminalCommandResponse:
    handled: bool
    content: str = ""


async def handle_terminal_command(
    *,
    content: str,
    user_id: int,
    is_owner: bool,
    trigger_prefix: str,
    terminal_service: TerminalService | None,
) -> TerminalCommandResponse:
    query = _parse_terminal_query(content=content, trigger_prefix=trigger_prefix)
    if query is None:
        return TerminalCommandResponse(handled=False)

    if not is_admin_user(user_id=user_id, is_owner=is_owner):
        return TerminalCommandResponse(
            handled=True,
            content=f"{X_MARK} You don't have permission to use terminal commands.",
        )

    if terminal_service is None:
        return TerminalCommandResponse(
            handled=True,
            content=f"{X_MARK} Terminal access is disabled.",
        )

    if not query:
        usage = f"{trigger_prefix.strip()} shell <command>"
        return TerminalCommandResponse(
            handled=True,
            content=f"{X_MARK} Usage: `{usage}`",
        )

    try:
        result = await terminal_service.run(query)
    except TerminalClientError as exc:
        return TerminalCommandResponse(
            handled=True,
            content=f"{X_MARK} Terminal error: {exc}",
        )

    return TerminalCommandResponse(
        handled=True,
        content=f"{CHECK_MARK} Terminal result\n\n{format_terminal_result(result)}",
    )


def _parse_terminal_query(*, content: str, trigger_prefix: str) -> str | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None

    remainder = text[len(prefix) :].lstrip()
    lowered = remainder.lower()
    for command in _TERMINAL_COMMANDS:
        if lowered == command:
            return ""
        if lowered.startswith(f"{command} "):
            return remainder[len(command) :].strip()
    return None
