from __future__ import annotations

from dataclasses import dataclass

from eva.constants import CHECK_MARK, X_MARK
from eva.discord.commands import is_admin_user


@dataclass(frozen=True, slots=True)
class ClearCommandResponse:
    handled: bool
    content: str = ""
    should_clear: bool = False


async def handle_clear_command(
    *,
    content: str,
    user_id: int,
    is_owner: bool,
    trigger_prefix: str,
) -> ClearCommandResponse:
    command = _parse_clear_command(content=content, trigger_prefix=trigger_prefix)
    if command is None:
        return ClearCommandResponse(handled=False)

    if not is_admin_user(user_id=user_id, is_owner=is_owner):
        return ClearCommandResponse(
            handled=True,
            content=f"{X_MARK} You don't have permission to clear channel memory.",
        )

    return ClearCommandResponse(
        handled=True,
        content=f"{CHECK_MARK} Cleared memory for this channel.",
        should_clear=True,
    )


def _parse_clear_command(*, content: str, trigger_prefix: str) -> str | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None

    remainder = text[len(prefix) :].strip().lower()
    if remainder == "clear":
        return remainder
    return None
