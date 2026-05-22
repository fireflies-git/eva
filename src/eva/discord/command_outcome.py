from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    handled: bool
    content: str = ""
    attachments: list[tuple[str, bytes]] | None = None
    should_clear: bool = False

    @classmethod
    def not_handled(cls) -> CommandOutcome:
        return cls(handled=False)
