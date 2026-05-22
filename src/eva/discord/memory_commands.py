"""Per-user memory commands: remember/forget/list."""

from __future__ import annotations

from dataclasses import dataclass

from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.state import UserMemoryError, UserMemoryPersistenceError, UserMemoryStore


@dataclass(frozen=True, slots=True)
class MemoryCommandResponse:
    handled: bool
    content: str = ""


_REMEMBER_ALIASES = ("remember",)
_FORGET_ALIASES = ("forget",)
_LIST_ALIASES = ("memories", "memory")


async def handle_memory_command(
    *,
    content: str,
    user_id: int,
    trigger_prefix: str,
    memory_store: UserMemoryStore,
) -> MemoryCommandResponse:
    parsed = _parse_memory_command(content=content, trigger_prefix=trigger_prefix)
    if parsed is None:
        return MemoryCommandResponse(handled=False)

    verb, argument = parsed

    if verb == "remember" and not argument:
        return _format_listing(memory_store, user_id)
    if verb in {"memories", "memory"}:
        return _format_listing(memory_store, user_id)
    if verb == "remember":
        return _handle_remember(memory_store, user_id=user_id, note=argument)
    if verb == "forget":
        return _handle_forget(memory_store, user_id=user_id, argument=argument)

    return MemoryCommandResponse(handled=False)


def format_memories_for_prompt(notes: list[str]) -> str | None:
    """Render stored notes for injection into requester_context."""
    if not notes:
        return None
    lines = ["Remembered facts about this requester:"]
    for index, note in enumerate(notes, start=1):
        lines.append(f"{index}. {note}")
    return "\n".join(lines)


def _format_listing(memory_store: UserMemoryStore, user_id: int) -> MemoryCommandResponse:
    notes = memory_store.get(user_id)
    if not notes:
        return MemoryCommandResponse(
            handled=True,
            content=(
                f"{WARNING_MARK} You have no remembered facts. "
                "Use `remember <text>` to add one."
            ),
        )
    body = "\n".join(f"{i}. {note}" for i, note in enumerate(notes, start=1))
    return MemoryCommandResponse(
        handled=True,
        content=f"{CHECK_MARK} Your remembered facts:\n{body}",
    )


def _handle_remember(
    memory_store: UserMemoryStore,
    *,
    user_id: int,
    note: str,
) -> MemoryCommandResponse:
    try:
        saved = memory_store.add(user_id, note)
    except UserMemoryError as exc:
        return MemoryCommandResponse(handled=True, content=f"{WARNING_MARK} {exc}")
    except UserMemoryPersistenceError:
        return MemoryCommandResponse(
            handled=True,
            content=f"{X_MARK} Failed to persist your memory. Try again later.",
        )
    return MemoryCommandResponse(handled=True, content=f"{CHECK_MARK} Remembered: {saved}")


def _handle_forget(
    memory_store: UserMemoryStore,
    *,
    user_id: int,
    argument: str,
) -> MemoryCommandResponse:
    normalized = argument.strip().lower()
    if not normalized:
        return MemoryCommandResponse(
            handled=True,
            content=f"{WARNING_MARK} Usage: `forget <N>` or `forget all`.",
        )

    if normalized == "all":
        try:
            removed = memory_store.clear(user_id)
        except UserMemoryPersistenceError:
            return MemoryCommandResponse(
                handled=True,
                content=f"{X_MARK} Failed to persist your memory. Try again later.",
            )
        if removed == 0:
            return MemoryCommandResponse(
                handled=True,
                content=f"{WARNING_MARK} You have no remembered facts to forget.",
            )
        return MemoryCommandResponse(
            handled=True,
            content=f"{CHECK_MARK} Forgot all {removed} of your remembered facts.",
        )

    try:
        index = int(normalized)
    except ValueError:
        return MemoryCommandResponse(
            handled=True,
            content=f"{WARNING_MARK} Usage: `forget <N>` or `forget all`.",
        )

    try:
        removed_note = memory_store.remove(user_id, index)
    except UserMemoryPersistenceError:
        return MemoryCommandResponse(
            handled=True,
            content=f"{X_MARK} Failed to persist your memory. Try again later.",
        )
    if removed_note is None:
        return MemoryCommandResponse(
            handled=True,
            content=f"{WARNING_MARK} No remembered fact at index {index}.",
        )
    return MemoryCommandResponse(handled=True, content=f"{CHECK_MARK} Forgot: {removed_note}")


def _parse_memory_command(*, content: str, trigger_prefix: str) -> tuple[str, str] | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None

    remainder = text[len(prefix) :].lstrip()
    lowered = remainder.lower()

    for verb in (*_REMEMBER_ALIASES, *_FORGET_ALIASES, *_LIST_ALIASES):
        if lowered == verb:
            return verb, ""
        if lowered.startswith(f"{verb} "):
            argument = remainder[len(verb) :].strip()
            # `forget reminder <id>` belongs to the reminder command handler.
            if verb == "forget" and argument.lower().startswith("reminder"):
                return None
            return verb, argument
    return None
