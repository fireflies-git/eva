"""AI-based image generation decision detector.

This detector is intentionally conservative: it should only return YES when the
user explicitly asks for an image to be generated.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from eva.ai.client import AIClientError, ChatCompletionClient
from eva.ai.parsing import parse_strict_yes_no
from eva.ai.schemas import ChatMessage
from eva.constants import MAX_IMAGE_DECISION_CONTEXT_MESSAGES
from eva.prompts import build_image_decision_prompt


@dataclass(frozen=True, slots=True)
class ImageDecision:
    should_generate: bool
    reason: str = ""


class ImageDetector:
    def __init__(self, *, client: ChatCompletionClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def should_generate(
        self,
        user_message: str,
        recent_context: Sequence[ChatMessage] | None = None,
        reply_context: str | None = None,
    ) -> ImageDecision:
        if not user_message.strip():
            return ImageDecision(should_generate=False)

        input_text = self._build_input(user_message, recent_context, reply_context)
        try:
            response = await self._client.chat_completion(
                messages=[
                    {"role": "system", "content": build_image_decision_prompt()},
                    {"role": "user", "content": input_text},
                ],
                model=self._model_name,
                temperature=0.0,
                max_tokens=5,
            )
        except AIClientError:
            return ImageDecision(should_generate=False, reason="ai-error")

        decision = parse_strict_yes_no(response)
        if decision is None:
            return ImageDecision(should_generate=False, reason="ai-invalid")
        return ImageDecision(should_generate=decision, reason="ai")

    def _build_input(
        self,
        user_message: str,
        recent_context: Sequence[ChatMessage] | None,
        reply_context: str | None,
    ) -> str:
        lines: list[str] = []

        if recent_context:
            relevant = recent_context[-MAX_IMAGE_DECISION_CONTEXT_MESSAGES:]
            lines.append("Recent chat:")
            lines.extend(f"  {msg['content']}" for msg in relevant)
            lines.append("")

        if reply_context:
            lines.append(f"Replying to: {reply_context}")
            lines.append("")

        lines.append(f"Message: {user_message}")
        return "\n".join(lines)
