from __future__ import annotations

import json
import logging
import re

from eva.ai.client import AIClientError, ChatCompletionClient
from eva.prompts.splitting import build_split_prompt

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


class ResponseSplitService:
    def __init__(self, *, client: ChatCompletionClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def split_reply(
        self,
        *,
        reply_content: str,
        first_limit: int,
        continuation_limit: int,
    ) -> list[str] | None:
        prompt = build_split_prompt(
            reply_content=reply_content,
            first_limit=first_limit,
            continuation_limit=continuation_limit,
        )

        try:
            response = await self._client.chat_completion(
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a JSON-only Discord message split planner. "
                            "Return valid JSON and nothing else."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                model=self._model_name,
                temperature=0.1,
                max_tokens=1200,
            )
        except AIClientError:
            logger.exception("AI split planning failed")
            return None

        return self._parse_split_response(
            response,
            reply_content=reply_content,
            first_limit=first_limit,
            continuation_limit=continuation_limit,
        )

    @staticmethod
    def _parse_split_response(
        response: str,
        *,
        reply_content: str,
        first_limit: int,
        continuation_limit: int,
    ) -> list[str] | None:
        candidate = response.strip()
        fence_match = _JSON_FENCE_RE.match(candidate)
        if fence_match is not None:
            candidate = fence_match.group(1).strip()

        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            logger.warning("Split planner returned invalid JSON: %r", response)
            return None

        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            logger.warning("Split planner returned invalid message payload: %r", payload)
            return None

        cleaned: list[str] = []
        for index, message in enumerate(messages):
            if not isinstance(message, str):
                return None
            chunk = message.strip()
            if not chunk:
                return None
            limit = first_limit if index == 0 else continuation_limit
            if len(chunk) > limit:
                logger.warning("Split planner chunk exceeded limit %s > %s", len(chunk), limit)
                return None
            cleaned.append(chunk)

        original_normalized = ResponseSplitService._collapse_whitespace(reply_content)
        rebuilt_normalized = ResponseSplitService._collapse_whitespace("\n\n".join(cleaned))
        if rebuilt_normalized != original_normalized:
            logger.warning("Split planner altered reply content; falling back to local splitting")
            return None

        return cleaned

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        return " ".join((text.strip() or "(empty response)").split())
