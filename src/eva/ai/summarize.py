"""Channel summarization service."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from eva.ai.client import AIClientError, ChatCompletionClient
from eva.ai.schemas import ChatMessage
from eva.prompts.summarize import build_summarize_system_prompt

logger = logging.getLogger(__name__)


SUMMARIZE_MAX_TOKENS = 1024
SUMMARIZE_TEMPERATURE = 0.4


class SummarizationService:
    def __init__(self, *, client: ChatCompletionClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def summarize(
        self,
        *,
        channel_messages: Sequence[ChatMessage],
        requester_context: str | None = None,
    ) -> str:
        if not channel_messages:
            raise SummarizationEmptyError("There are no recent messages to summarize.")

        joined = "\n".join(
            self._format_message_line(message) for message in channel_messages
        )

        user_prompt_parts = []
        if requester_context:
            user_prompt_parts.append(
                f"Requester context (for tone, not summary content):\n{requester_context}"
            )
        user_prompt_parts.append(f"Channel messages to summarize:\n{joined}")
        user_prompt = "\n\n".join(user_prompt_parts)

        messages: list[ChatMessage] = [
            {"role": "system", "content": build_summarize_system_prompt()},
            {"role": "user", "content": user_prompt},
        ]

        return await self._client.chat_completion(
            messages=messages,
            model=self._model_name,
            temperature=SUMMARIZE_TEMPERATURE,
            max_tokens=SUMMARIZE_MAX_TOKENS,
        )

    @staticmethod
    def _format_message_line(message: ChatMessage) -> str:
        # Channel context messages are already formatted like "[HH:MM] user(...): text"
        # by fetch_channel_context, so just unwrap the content here.
        content = message.get("content", "")
        return content


class SummarizationEmptyError(AIClientError):
    """Raised when there is nothing to summarize."""
