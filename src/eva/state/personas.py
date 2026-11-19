"""Persistent custom persona library with per-user and per-channel activation."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from eva.state.atomic import validate_state_path, write_text_atomic

logger = logging.getLogger(__name__)

DEFAULT_PERSONAS_PATH = Path("personas.json")
DEFAULT_MAX_PERSONAS = 25
DEFAULT_MAX_NAME_CHARS = 32
DEFAULT_MAX_INSTRUCTION_CHARS = 1500

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class PersonaError(ValueError):
    """Raised for user-visible persona errors (bad name, too long, unknown persona)."""


class PersonaPersistenceError(RuntimeError):
    """Raised when a persona mutation cannot be persisted to disk."""


@dataclass(frozen=True, slots=True)
class Persona:
    name: str
    instructions: str
    created_by: int


@dataclass(slots=True)
class _Snapshot:
    personas: dict[str, Persona]
    user_active: dict[int, str]
    channel_active: dict[int, str]


class PersonaStore:
    def __init__(
        self,
        *,
        path: Path = DEFAULT_PERSONAS_PATH,
        max_personas: int = DEFAULT_MAX_PERSONAS,
        max_name_chars: int = DEFAULT_MAX_NAME_CHARS,
        max_instruction_chars: int = DEFAULT_MAX_INSTRUCTION_CHARS,
    ) -> None:
        if max_personas <= 0:
            raise ValueError("max_personas must be positive")
        if max_name_chars <= 0:
            raise ValueError("max_name_chars must be positive")
        if max_instruction_chars <= 0:
            raise ValueError("max_instruction_chars must be positive")
        self._path = validate_state_path(path)
        self._max_personas = max_personas
        self._max_name_chars = max_name_chars
        self._max_instruction_chars = max_instruction_chars
        self._personas: dict[str, Persona] = {}
        self._user_active: dict[int, str] = {}
        self._channel_active: dict[int, str] = {}
        self._load()

    @property
    def max_personas(self) -> int:
        return self._max_personas

    @property
    def max_instruction_chars(self) -> int:
        return self._max_instruction_chars

    # -- persistence ---------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load personas from %s", self._path)
            return
        if not isinstance(data, dict):
            logger.warning("Persona file %s is not an object; ignoring", self._path)
            return
        self._load_personas(data.get("personas"))
        self._user_active = self._load_activations(data.get("user_active"))
        self._channel_active = self._load_activations(data.get("channel_active"))

    def _load_personas(self, raw: object) -> None:
        if not isinstance(raw, dict):
            return
        for raw_name, raw_persona in raw.items():
            if not isinstance(raw_persona, dict) or not isinstance(raw_name, str):
                continue
            instructions = raw_persona.get("instructions")
            created_by = raw_persona.get("created_by")
            if not isinstance(instructions, str) or not instructions.strip():
                continue
            if not isinstance(created_by, int) or isinstance(created_by, bool):
                continue
            if _NAME_RE.match(raw_name) is None:
                continue
            if len(self._personas) >= self._max_personas:
                break
            self._personas[raw_name] = Persona(
                name=raw_name,
                instructions=instructions.strip()[: self._max_instruction_chars],
                created_by=created_by,
            )

    def _load_activations(self, raw: object) -> dict[int, str]:
        if not isinstance(raw, dict):
            return {}
        activations: dict[int, str] = {}
        for raw_id, name in raw.items():
            try:
                target_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if isinstance(name, str) and name in self._personas:
                activations[target_id] = name
        return activations

    def _save(self) -> bool:
        payload = {
            "personas": {
                name: {"instructions": persona.instructions, "created_by": persona.created_by}
                for name, persona in self._personas.items()
            },
            "user_active": {str(key): value for key, value in self._user_active.items()},
            "channel_active": {str(key): value for key, value in self._channel_active.items()},
        }
        try:
            write_text_atomic(self._path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
            return True
        except Exception:
            logger.exception("Failed to save personas to %s", self._path)
            return False

    def _snapshot(self) -> _Snapshot:
        return _Snapshot(
            personas=dict(self._personas),
            user_active=dict(self._user_active),
            channel_active=dict(self._channel_active),
        )

    def _commit_or_restore(self, snapshot: _Snapshot, action: str) -> None:
        if self._save():
            return
        self._personas = snapshot.personas
        self._user_active = snapshot.user_active
        self._channel_active = snapshot.channel_active
        raise PersonaPersistenceError(f"Failed to persist persona {action}")

    # -- validation ----------------------------------------------------------

    def _normalize_name(self, name: str) -> str:
        normalized = name.strip().lower()
        if not normalized:
            raise PersonaError("Persona name is empty.")
        if len(normalized) > self._max_name_chars:
            raise PersonaError(
                f"Persona name is too long ({len(normalized)} > {self._max_name_chars} chars)."
            )
        if _NAME_RE.match(normalized) is None:
            raise PersonaError(
                "Persona names may only use letters, numbers, `-` and `_`."
            )
        return normalized

    def _clean_instructions(self, instructions: str) -> str:
        cleaned = instructions.strip()
        if not cleaned:
            raise PersonaError("Persona instructions are empty.")
        if len(cleaned) > self._max_instruction_chars:
            raise PersonaError(
                f"Persona instructions are too long "
                f"({len(cleaned)} > {self._max_instruction_chars} chars)."
            )
        return cleaned

    def _require(self, name: str) -> Persona:
        normalized = name.strip().lower()
        persona = self._personas.get(normalized)
        if persona is None:
            raise PersonaError(f"No persona named `{normalized or name.strip()}`.")
        return persona

    # -- library -------------------------------------------------------------

    def get(self, name: str) -> Persona | None:
        return self._personas.get(name.strip().lower())

    def list(self) -> list[Persona]:
        return [self._personas[key] for key in sorted(self._personas)]

    def create(self, *, name: str, instructions: str, created_by: int) -> Persona:
        normalized = self._normalize_name(name)
        cleaned = self._clean_instructions(instructions)
        if normalized in self._personas:
            raise PersonaError(f"Persona `{normalized}` already exists. Use `persona edit`.")
        if len(self._personas) >= self._max_personas:
            raise PersonaError(
                f"There are already {self._max_personas} personas. Delete one first."
            )
        snapshot = self._snapshot()
        persona = Persona(name=normalized, instructions=cleaned, created_by=created_by)
        self._personas[normalized] = persona
        self._commit_or_restore(snapshot, "create")
        return persona

    def update(self, *, name: str, instructions: str) -> Persona:
        existing = self._require(name)
        cleaned = self._clean_instructions(instructions)
        snapshot = self._snapshot()
        persona = Persona(
            name=existing.name, instructions=cleaned, created_by=existing.created_by
        )
        self._personas[existing.name] = persona
        self._commit_or_restore(snapshot, "update")
        return persona

    def delete(self, name: str) -> Persona:
        existing = self._require(name)
        snapshot = self._snapshot()
        del self._personas[existing.name]
        self._user_active = {k: v for k, v in self._user_active.items() if v != existing.name}
        self._channel_active = {
            k: v for k, v in self._channel_active.items() if v != existing.name
        }
        self._commit_or_restore(snapshot, "delete")
        return existing

    # -- activation ----------------------------------------------------------

    def set_user_active(self, user_id: int, name: str) -> Persona:
        persona = self._require(name)
        snapshot = self._snapshot()
        self._user_active[user_id] = persona.name
        self._commit_or_restore(snapshot, "activation")
        return persona

    def clear_user_active(self, user_id: int) -> bool:
        if user_id not in self._user_active:
            return False
        snapshot = self._snapshot()
        del self._user_active[user_id]
        self._commit_or_restore(snapshot, "reset")
        return True

    def set_channel_active(self, channel_id: int, name: str) -> Persona:
        persona = self._require(name)
        snapshot = self._snapshot()
        self._channel_active[channel_id] = persona.name
        self._commit_or_restore(snapshot, "channel activation")
        return persona

    def clear_channel_active(self, channel_id: int) -> bool:
        if channel_id not in self._channel_active:
            return False
        snapshot = self._snapshot()
        del self._channel_active[channel_id]
        self._commit_or_restore(snapshot, "channel reset")
        return True

    def get_user_active(self, user_id: int) -> Persona | None:
        name = self._user_active.get(user_id)
        return self._personas.get(name) if name is not None else None

    def get_channel_active(self, channel_id: int) -> Persona | None:
        name = self._channel_active.get(channel_id)
        return self._personas.get(name) if name is not None else None

    def resolve(self, user_id: int | None, channel_id: int | None) -> Persona | None:
        """Return the user's persona, else the channel's, else None."""
        if user_id is not None:
            persona = self.get_user_active(user_id)
            if persona is not None:
                return persona
        if channel_id is not None:
            return self.get_channel_active(channel_id)
        return None
