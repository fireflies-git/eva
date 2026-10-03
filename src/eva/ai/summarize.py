"""Channel summarization service."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from eva.ai.client import AIClientError, ChatCompletionClient
from eva.ai.schemas import ChatMessage, ContentPart, visible_text
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

        joined = "\n".join(self._format_message_line(message) for message in channel_messages)

        user_prompt_parts = []
        if requester_context:
            user_prompt_parts.append(
                "[UNTRUSTED_REQUESTER_CONTEXT] (for tone, not summary content):\n"
                f"{requester_context}"
            )
        user_prompt_parts.append("[UNTRUSTED_DISCORD_DATA] Channel messages to summarize:")
        user_prompt = "\n\n".join(user_prompt_parts)
        media_parts = _summary_media_parts(channel_messages)
        if media_parts is None:
            user_prompt = f"{user_prompt}\n{joined}"

        messages: list[ChatMessage] = [
            {"role": "system", "content": build_summarize_system_prompt()},
            {
                "role": "user",
                "content": (
                    user_prompt
                    if media_parts is None
                    else [
                        {"type": "text", "text": f"{user_prompt}\n{joined}"},
                        *media_parts,
                    ]
                ),
            },
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
        return visible_text(message)


class SummarizationEmptyError(AIClientError):
    """Raised when there is nothing to summarize."""


def _summary_media_parts(messages: Sequence[ChatMessage]) -> list[ContentPart] | None:
    parts: list[ContentPart] = []
    for message in messages:
        content = message["content"]
        if not isinstance(content, list):
            continue
        parts.extend(content)
    return parts or None
