from __future__ import annotations

from eva.ai.client import OpenAICompatibleClient
from eva.ai.schemas import ChatMessage


class ResponseService:
    def __init__(self, *, client: OpenAICompatibleClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def generate_reply(
        self,
        *,
        system_prompt: str,
        context_messages: list[ChatMessage],
        history_messages: list[ChatMessage],
        user_message: str,
        reply_context: str | None,
    ) -> str:
        full_user_message = user_message
        if reply_context:
            full_user_message = f'[Replying to message: "{reply_context}"]\n\n{user_message}'

        messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        messages.extend(context_messages)
        messages.extend(history_messages)
        messages.append({"role": "user", "content": full_user_message})

        return await self._client.chat_completion(
            messages=messages,
            model=self._model_name,
            temperature=0.7,
            max_tokens=1024,
        )
