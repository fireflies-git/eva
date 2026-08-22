"""AI helper that reviews incoming friend request profiles."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from eva.ai.client import AIClientError, ChatCompletionClient
from eva.ai.schemas import ChatMessage
from eva.prompts.builder import build_friend_request_review_prompt

logger = logging.getLogger(__name__)

RECOMMENDATIONS = frozenset({"accept", "deny", "unsure"})


@dataclass(frozen=True, slots=True)
class FriendRequestReview:
    message: str
    recommendation: str


class FriendRequestReviewService:
    def __init__(
        self,
        *,
        client: ChatCompletionClient,
        model_name: str,
        account_mode: str = "assistant",
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._system_prompt = build_friend_request_review_prompt(
            account_mode=account_mode
        )

    async def review(self, profile_text: str) -> FriendRequestReview | None:
        messages: list[ChatMessage] = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": profile_text},
        ]
        try:
            response = await self._client.chat_completion(
                messages=messages,
                model=self._model_name,
                temperature=0.0,
                max_tokens=300,
            )
        except AIClientError:
            logger.exception("Friend request review failed")
            return None

        payload = _parse_json_object(response)
        if payload is None:
            logger.warning("Friend request review returned invalid JSON: %r", response)
            return None

        message = _clean_text(payload.get("message"))
        recommendation = _clean_text(payload.get("recommendation")).lower()
        if not message or recommendation not in RECOMMENDATIONS:
            logger.warning(
                "Friend request review missing message/recommendation: %r",
                payload,
            )
            return None
        return FriendRequestReview(message=message, recommendation=recommendation)


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


def _clean_text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.strip().split())
