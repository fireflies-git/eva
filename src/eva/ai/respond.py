from __future__ import annotations

from eva.ai.client import OpenAICompatibleClient
from eva.ai.schemas import ChatMessage
from eva.search.schemas import SearchResultBundle

MAX_SEARCH_RESULTS = 5


def _build_user_message(user_message: str, reply_context: str | None) -> str:
    if not reply_context:
        return user_message
    return f'[Replying to message: "{reply_context}"]\n\n{user_message}'


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
        messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        messages.extend(history_messages)
        messages.extend(context_messages)
        messages.append(
            {"role": "user", "content": _build_user_message(user_message, reply_context)}
        )

        return await self._client.chat_completion(
            messages=messages,
            model=self._model_name,
            temperature=0.7,
            max_tokens=2048,
            allow_reasoning_fallback=True,
        )


class SearchResponseService:
    def __init__(self, *, client: OpenAICompatibleClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def generate_reply(
        self,
        *,
        system_prompt: str,
        search_results: SearchResultBundle,
        recent_context: list[ChatMessage],
        user_message: str,
        reply_context: str | None,
    ) -> str:
        messages: list[ChatMessage] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": self._build_search_input(
                    search_results=search_results,
                    recent_context=recent_context,
                    user_message=user_message,
                    reply_context=reply_context,
                ),
            },
        ]

        return await self._client.chat_completion(
            messages=messages,
            model=self._model_name,
            temperature=0.2,
            max_tokens=2048,
            allow_reasoning_fallback=True,
        )

    def _build_search_input(
        self,
        *,
        search_results: SearchResultBundle,
        recent_context: list[ChatMessage],
        user_message: str,
        reply_context: str | None,
    ) -> str:
        lines = [
            f"User request: {_build_user_message(user_message, reply_context)}",
        ]

        relevant_context = recent_context[-3:]
        if relevant_context:
            lines.append("")
            lines.append("Recent channel context:")
            lines.extend(f"- {message['content']}" for message in relevant_context)

        lines.append("")
        lines.append(f"Google query: {search_results.query}")

        if search_results.answer_box is not None:
            lines.append("")
            lines.append("Answer box:")
            lines.append(f"- Title: {search_results.answer_box.title}")
            lines.append(f"- Answer: {search_results.answer_box.answer}")
            if search_results.answer_box.link:
                lines.append(f"- Link: {search_results.answer_box.link}")

        if search_results.knowledge_graph is not None:
            lines.append("")
            lines.append("Knowledge graph:")
            lines.append(f"- Title: {search_results.knowledge_graph.title}")
            lines.append(f"- Description: {search_results.knowledge_graph.description}")
            if search_results.knowledge_graph.source:
                lines.append(f"- Source: {search_results.knowledge_graph.source}")
            if search_results.knowledge_graph.source_link:
                lines.append(f"- Source link: {search_results.knowledge_graph.source_link}")

        if search_results.organic_results:
            lines.append("")
            lines.append("Organic results:")
            for result in search_results.organic_results[:MAX_SEARCH_RESULTS]:
                lines.append(f"- [{result.position}] {result.title}")
                lines.append(f"  Link: {result.link}")
                lines.append(f"  Snippet: {result.snippet}")
                if result.date:
                    lines.append(f"  Date: {result.date}")

        return "\n".join(lines)


class TOSCheckService:
    def __init__(self, *, client: OpenAICompatibleClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def check_tos_violation(self, text: str) -> bool:
        system_prompt = (
            "You are a strict Discord TOS moderator. Analyze the following text and determine if it violates Discord's Terms of Service, "
            "specifically checking for:\n"
            "1. Claims of being underage (e.g. 'I am 12', 'im 11', etc.)\n"
            "2. The hard-R n-word.\n"
            "3. Extreme hate speech or illegal content.\n\n"
            "Note: General swearing and mild slurs (like 'faggot' or 'retard') are permitted by the owner in this context. "
            "Only flag strict TOS violations like underage claims, the hard-R n-word, or extreme illegal/harmful content.\n\n"
            "Reply with exactly 'YES' if it violates these rules, or 'NO' if it is acceptable. Say nothing else."
        )

        try:
            response = await self._client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                model=self._model_name,
                temperature=0.0,
                max_tokens=10,
            )
            return "YES" in response.upper()
        except Exception:
            return False
