"""Admin command for toggling Eva's response watermark."""

from __future__ import annotations

from typing import Protocol

from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.discord.command_outcome import CommandOutcome
from eva.discord.commands import is_admin_user

_ACTIONS = frozenset({"on", "off", "enable", "disable", "status"})


class WatermarkController(Protocol):
    @property
    def watermark_enabled(self) -> bool: ...

    def set_watermark_enabled(self, enabled: bool) -> None: ...


async def handle_watermark_command(
    *,
    content: str,
    user_id: int,
    is_owner: bool,
    trigger_prefix: str,
    controller: WatermarkController,
) -> CommandOutcome:
    action = _parse_watermark_action(content=content, trigger_prefix=trigger_prefix)
    if action is None:
        return CommandOutcome.not_handled()

    if not is_admin_user(user_id=user_id, is_owner=is_owner):
        return CommandOutcome(
            handled=True,
            content=f"{X_MARK} You don't have permission to change the watermark.",
        )

    if action == "invalid":
        usage = f"{trigger_prefix.strip()} watermark <on|off|status>"
        return CommandOutcome(handled=True, content=f"{X_MARK} Usage: `{usage}`")

    if action == "status":
        state = "enabled" if controller.watermark_enabled else "disabled"
        return CommandOutcome(
            handled=True,
            content=f"{WARNING_MARK} Watermark is {state}.",
        )

    enabled = action in {"on", "enable"}
    controller.set_watermark_enabled(enabled)
    state = "enabled" if enabled else "disabled"
    return CommandOutcome(
        handled=True,
        content=f"{CHECK_MARK} Watermark {state}.",
    )


def _parse_watermark_action(*, content: str, trigger_prefix: str) -> str | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None

    remainder = text[len(prefix) :].strip().lower()
    parts = remainder.split()
    if not parts or parts[0] != "watermark":
        return None
    if len(parts) == 1:
        return "status"
    if len(parts) != 2 or parts[1] not in _ACTIONS:
        return "invalid"
    return parts[1]
