from __future__ import annotations

import json
import logging
import re
from typing import Any

from eva.account_updates import (
    AccountUpdateDraft,
    AccountUpdatePlan,
    validate_account_update_draft,
)
from eva.ai.client import AIClientError, ChatCompletionClient
from eva.ai.schemas import ChatMessage

logger = logging.getLogger(__name__)

_ACCOUNT_UPDATE_SYSTEM_PROMPT = (
    "You detect explicit requests to change Eva's own Discord account profile or presence.\n"
    "Return only JSON with this exact shape:\n"
    "{\n"
    '  "is_account_update": boolean,\n'
    '  "display_name": {"action": "none|set|clear", "value": string|null},\n'
    '  "bio": {"action": "none|set|clear", "value": string|null},\n'
    '  "presence": {"action": "none|set", "value": "online|idle|dnd|invisible"|null},\n'
    '  "custom_status": {"action": "none|set|clear", "value": string|null}\n'
    "}\n\n"
    "Only set is_account_update true when the user is explicitly asking to change Eva's "
    "own Discord account details: display name, bio/about-me, online presence, or custom "
    "status. Eva runs as the user's Discord account, so first-person wording like 'my "
    "display name' or second-person wording like 'your display name' can both refer to "
    "Eva's account when phrased as a change request. Questions about status/profile, "
    "jokes, or requests about another user are false. For clearing a field, use action "
    "clear. Do not include markdown."
)

_ACCOUNT_UPDATE_TARGETS = (
    "display name",
    "bio",
    "about me",
    "profile",
    "custom status",
    "status",
    "presence",
    "online",
    "idle",
    "dnd",
    "invisible",
)
_ACCOUNT_UPDATE_VERBS = (
    "set",
    "change",
    "update",
    "make",
    "clear",
    "remove",
    "switch",
    "go",
)


class AccountUpdatePlanner:
    def __init__(self, *, client: ChatCompletionClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def plan_update(self, user_message: str) -> AccountUpdatePlan | None:
        if not _could_be_account_update(user_message):
            return None

        messages: list[ChatMessage] = [
            {"role": "system", "content": _ACCOUNT_UPDATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        try:
            response = await self._client.chat_completion(
                messages=messages,
                model=self._model_name,
                temperature=0.0,
                max_tokens=350,
            )
        except AIClientError:
            logger.exception("Account update planner failed")
            return None

        payload = _parse_json_object(response)
        if payload is None:
            logger.warning("Account update planner returned invalid JSON: %r", response)
            return None
        if payload.get("is_account_update") is not True:
            return None

        draft = _build_draft(payload)
        error = validate_account_update_draft(draft)
        if error is not None:
            return AccountUpdatePlan(error=error)
        return AccountUpdatePlan(draft=draft)


def _could_be_account_update(text: str) -> bool:
    lowered = text.lower()
    return any(verb in lowered for verb in _ACCOUNT_UPDATE_VERBS) and any(
        target in lowered for target in _ACCOUNT_UPDATE_TARGETS
    )


def _parse_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.DOTALL)
    if fenced is not None:
        stripped = fenced.group(1).strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _build_draft(payload: dict[str, Any]) -> AccountUpdateDraft:
    display_name, clear_display_name = _parse_text_change(payload.get("display_name"))
    bio, clear_bio = _parse_text_change(payload.get("bio"))
    custom_status, clear_custom_status = _parse_text_change(payload.get("custom_status"))
    presence = _parse_presence_change(payload.get("presence"))

    return AccountUpdateDraft(
        display_name=display_name,
        clear_display_name=clear_display_name,
        bio=bio,
        clear_bio=clear_bio,
        presence=presence,
        custom_status=custom_status,
        clear_custom_status=clear_custom_status,
    )


def _parse_text_change(raw: object) -> tuple[str | None, bool]:
    if not isinstance(raw, dict):
        return None, False

    action = raw.get("action")
    if not isinstance(action, str):
        return None, False
    normalized = action.strip().lower()

    if normalized == "clear":
        return None, True
    if normalized != "set":
        return None, False

    value = raw.get("value")
    if not isinstance(value, str):
        return None, False
    cleaned = _clean_text(value)
    return (cleaned, False) if cleaned else (None, False)


def _parse_presence_change(raw: object) -> str | None:
    if not isinstance(raw, dict):
        return None

    action = raw.get("action")
    if not isinstance(action, str) or action.strip().lower() != "set":
        return None

    value = raw.get("value")
    if not isinstance(value, str):
        return None
    cleaned = _clean_text(value).lower()
    if cleaned == "do not disturb":
        return "dnd"
    return cleaned or None


def _clean_text(value: str) -> str:
    return " ".join(value.strip().split())
