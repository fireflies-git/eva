"""AI-based search decision detector."""

from __future__ import annotations

from dataclasses import dataclass

from eva.ai.client import AIClientError, OpenAICompatibleClient
from eva.ai.schemas import ChatMessage

MAX_CONTEXT_MESSAGES = 5

_SYSTEM_PROMPT = (
    "You decide whether a web search is needed to answer a message in a Discord chat.\n\n"
    "Reply with exactly YES or NO — nothing else.\n\n"
    "Reply YES if the message asks about:\n"
    "- Current events, news, prices, scores, or anything time-sensitive\n"
    "- Facts about real-world people, companies, products, or places\n"
    "- Something that requires up-to-date information to answer accurately\n"
    "- A topic where the conversation context alone is clearly not enough\n\n"
    "Reply NO if the message is:\n"
    "- Casual chat, opinions, jokes, or banter\n"
    "- A question answerable from the chat context already provided\n"
    "- A creative writing or roleplay request\n"
    "- A question about the bot itself or the conversation"
)


@dataclass(frozen=True, slots=True)
class SearchDecision:
    should_search: bool
    reason: str = ""


class SearchDetector:
    def __init__(self, *, client: OpenAICompatibleClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def should_search(
        self,
        user_message: str,
        recent_context: list[ChatMessage] | None = None,
        reply_context: str | None = None,
    ) -> SearchDecision:
        if not user_message.strip():
            return SearchDecision(should_search=False)

        input_text = self._build_input(user_message, recent_context, reply_context)

        try:
            response = await self._client.chat_completion(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": input_text},
                ],
                model=self._model_name,
                temperature=0.0,
                max_tokens=5,
            )
        except AIClientError:
            return SearchDecision(should_search=False, reason="ai-error")

        result = response.strip().upper()
        return SearchDecision(should_search="YES" in result, reason="ai")

    def _build_input(
        self,
        user_message: str,
        recent_context: list[ChatMessage] | None,
        reply_context: str | None,
    ) -> str:
        lines: list[str] = []

        if recent_context:
            relevant = recent_context[-MAX_CONTEXT_MESSAGES:]
            lines.append("Recent chat:")
            lines.extend(f"  {msg['content']}" for msg in relevant)
            lines.append("")

        if reply_context:
            lines.append(f"Replying to: {reply_context}")
            lines.append("")

        lines.append(f"Message: {user_message}")
        return "\n".join(lines)
