"""Custom persona commands: create/edit/delete (admin), list/show/use/reset, channel (admin)."""

from __future__ import annotations

from eva.constants import CHECK_MARK, WARNING_MARK, X_MARK
from eva.discord.command_outcome import CommandOutcome
from eva.state import PersonaError, PersonaPersistenceError, PersonaStore

_ADMIN_VERBS = frozenset({"create", "edit", "delete", "channel"})
_PERSIST_FAILURE = f"{X_MARK} Failed to persist personas. Try again later."
_USAGE = (
    f"{WARNING_MARK} Usage: `persona list`, `persona show <name>`, `persona use <name>`, "
    "`persona reset`. Admins: `persona create <name> <instructions>`, "
    "`persona edit <name> <instructions>`, `persona delete <name>`, "
    "`persona channel <name|reset>`."
)


async def handle_persona_command(
    *,
    content: str,
    user_id: int,
    channel_id: int,
    trigger_prefix: str,
    is_admin: bool,
    persona_store: PersonaStore,
) -> CommandOutcome:
    parsed = _parse_persona_command(content=content, trigger_prefix=trigger_prefix)
    if parsed is None:
        return CommandOutcome.not_handled()

    verb, argument = parsed
    if verb in _ADMIN_VERBS and not is_admin:
        return _reply(f"{WARNING_MARK} Only the owner and admins can manage personas.")

    try:
        return _dispatch(
            verb=verb,
            argument=argument,
            user_id=user_id,
            channel_id=channel_id,
            persona_store=persona_store,
        )
    except PersonaError as exc:
        return _reply(f"{WARNING_MARK} {exc}")
    except PersonaPersistenceError:
        return _reply(_PERSIST_FAILURE)


def _dispatch(
    *,
    verb: str,
    argument: str,
    user_id: int,
    channel_id: int,
    persona_store: PersonaStore,
) -> CommandOutcome:
    if verb == "list":
        return _handle_list(persona_store, user_id=user_id, channel_id=channel_id)
    if verb == "show":
        return _handle_show(persona_store, name=argument)
    if verb == "use":
        return _handle_use(persona_store, user_id=user_id, name=argument)
    if verb == "reset":
        return _handle_reset(persona_store, user_id=user_id)
    if verb == "create":
        return _handle_create(persona_store, user_id=user_id, argument=argument)
    if verb == "edit":
        return _handle_edit(persona_store, argument=argument)
    if verb == "delete":
        return _handle_delete(persona_store, name=argument)
    if verb == "channel":
        return _handle_channel(persona_store, channel_id=channel_id, argument=argument)
    return _reply(_USAGE)


def _reply(content: str) -> CommandOutcome:
    return CommandOutcome(handled=True, content=content)


def _split_name_and_instructions(argument: str) -> tuple[str, str]:
    name, _, instructions = argument.strip().partition(" ")
    return name, instructions.strip()


def _handle_list(persona_store: PersonaStore, *, user_id: int, channel_id: int) -> CommandOutcome:
    personas = persona_store.list()
    if not personas:
        return _reply(f"{WARNING_MARK} No personas exist yet.")
    lines = [f"{CHECK_MARK} Personas:"]
    lines.extend(f"- `{persona.name}`" for persona in personas)
    mine = persona_store.get_user_active(user_id)
    channel = persona_store.get_channel_active(channel_id)
    lines.append(f"Yours: {f'`{mine.name}`' if mine else 'none'}")
    lines.append(f"This channel: {f'`{channel.name}`' if channel else 'none'}")
    return _reply("\n".join(lines))


def _handle_show(persona_store: PersonaStore, *, name: str) -> CommandOutcome:
    if not name.strip():
        return _reply(f"{WARNING_MARK} Usage: `persona show <name>`.")
    persona = persona_store.get(name)
    if persona is None:
        return _reply(f"{WARNING_MARK} No persona named `{name.strip().lower()}`.")
    return _reply(f"{CHECK_MARK} `{persona.name}`:\n>>> {persona.instructions}")


def _handle_use(persona_store: PersonaStore, *, user_id: int, name: str) -> CommandOutcome:
    if not name.strip():
        return _reply(f"{WARNING_MARK} Usage: `persona use <name>`.")
    persona = persona_store.set_user_active(user_id, name)
    return _reply(f"{CHECK_MARK} You're now talking to Eva as `{persona.name}`.")


def _handle_reset(persona_store: PersonaStore, *, user_id: int) -> CommandOutcome:
    if not persona_store.clear_user_active(user_id):
        return _reply(f"{WARNING_MARK} You have no active persona.")
    return _reply(f"{CHECK_MARK} Persona reset.")


def _handle_create(persona_store: PersonaStore, *, user_id: int, argument: str) -> CommandOutcome:
    name, instructions = _split_name_and_instructions(argument)
    if not name or not instructions:
        return _reply(f"{WARNING_MARK} Usage: `persona create <name> <instructions>`.")
    persona = persona_store.create(name=name, instructions=instructions, created_by=user_id)
    return _reply(f"{CHECK_MARK} Created persona `{persona.name}`.")


def _handle_edit(persona_store: PersonaStore, *, argument: str) -> CommandOutcome:
    name, instructions = _split_name_and_instructions(argument)
    if not name or not instructions:
        return _reply(f"{WARNING_MARK} Usage: `persona edit <name> <instructions>`.")
    persona = persona_store.update(name=name, instructions=instructions)
    return _reply(f"{CHECK_MARK} Updated persona `{persona.name}`.")


def _handle_delete(persona_store: PersonaStore, *, name: str) -> CommandOutcome:
    if not name.strip():
        return _reply(f"{WARNING_MARK} Usage: `persona delete <name>`.")
    persona = persona_store.delete(name)
    return _reply(f"{CHECK_MARK} Deleted persona `{persona.name}`.")


def _handle_channel(
    persona_store: PersonaStore, *, channel_id: int, argument: str
) -> CommandOutcome:
    name = argument.strip()
    if not name:
        return _reply(f"{WARNING_MARK} Usage: `persona channel <name>` or `persona channel reset`.")
    if name.lower() == "reset":
        if not persona_store.clear_channel_active(channel_id):
            return _reply(f"{WARNING_MARK} This channel has no active persona.")
        return _reply(f"{CHECK_MARK} Channel persona reset.")
    persona = persona_store.set_channel_active(channel_id, name)
    return _reply(f"{CHECK_MARK} This channel now uses persona `{persona.name}`.")


def _parse_persona_command(*, content: str, trigger_prefix: str) -> tuple[str, str] | None:
    text = content.strip()
    prefix = trigger_prefix.strip()
    if not text.lower().startswith(prefix.lower()):
        return None

    remainder = text[len(prefix) :].lstrip()
    lowered = remainder.lower()
    if lowered == "persona" or lowered == "personas":
        return "list", ""
    if not lowered.startswith("persona "):
        return None

    body = remainder[len("persona") :].strip()
    verb, _, argument = body.partition(" ")
    return verb.lower(), argument.strip()
