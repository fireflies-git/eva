from __future__ import annotations

import re
from collections.abc import Sequence

from eva.ai.client import AIClientError, ChatCompletionClient
from eva.ai.schemas import ChatMessage
from eva.constants import MAX_QUERY_CONTEXT_MESSAGES, SEARCH_REWRITE_MAX_TOKENS

REFERENTIAL_PATTERN = re.compile(
    r"\b(it|they|them|that|this|those|these|he|she|him|her|what about|how about|and)\b",
    re.IGNORECASE,
)


class SearchQueryBuilder:
    def __init__(self, *, client: ChatCompletionClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def build_query(
        self,
        *,
        user_message: str,
        recent_context: Sequence[ChatMessage],
        reply_context: str | None,
    ) -> str:
        base_query = user_message.strip()
        if not base_query:
            return ""
        if not self._should_rewrite(base_query, reply_context):
            return base_query

        messages: list[ChatMessage] = [
            {"role": "system", "content": self._build_rewrite_prompt()},
            {
                "role": "user",
                "content": self._build_rewrite_input(
                    user_message=base_query,
                    recent_context=recent_context,
                    reply_context=reply_context,
                ),
            },
        ]

        try:
            rewritten = await self._client.chat_completion(
                messages=messages,
                model=self._model_name,
                temperature=0.1,
                max_tokens=SEARCH_REWRITE_MAX_TOKENS,
            )
        except AIClientError:
            return base_query

        cleaned = rewritten.strip().splitlines()[0].strip().strip('"')
        return cleaned or base_query

    def _should_rewrite(self, user_message: str, reply_context: str | None) -> bool:
        if reply_context:
            return True
        if len(user_message.split()) <= 6 and REFERENTIAL_PATTERN.search(user_message):
            return True
        lowered = user_message.lower()
        return lowered.startswith(("what about", "how about", "and ", "what if"))

    def _build_rewrite_prompt(self) -> str:
        return (
            "Rewrite the user's request into one standalone Google search query. "
            "Resolve pronouns and references using the provided chat context when needed. "
            "Return only the query text."
        )

    def _build_rewrite_input(
        self,
        *,
        user_message: str,
        recent_context: Sequence[ChatMessage],
        reply_context: str | None,
    ) -> str:
        lines = [f"User message: {user_message}"]
        if reply_context:
            lines.append(f"Reply context: {reply_context}")

        relevant_context = recent_context[-MAX_QUERY_CONTEXT_MESSAGES:]
        if relevant_context:
            lines.append("Recent messages:")
            lines.extend(f"- {message['content']}" for message in relevant_context)

        return "\n".join(lines)
