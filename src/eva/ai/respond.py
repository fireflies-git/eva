from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from eva.ai.client import (
    AIClientError,
    ChatCompletionClient,
    ModelToolCall,
    ToolChatCompletionClient,
)
from eva.ai.parsing import parse_strict_yes_no
from eva.ai.schemas import ChatMessage, ToolCall
from eva.constants import (
    MAX_SEARCH_REPLY_CONTEXT_MESSAGES,
    MAX_SEARCH_RESULTS,
    REPLY_MAX_TOKENS,
    SEARCH_REPLY_MAX_TOKENS,
)
from eva.search.schemas import SearchResultBundle
from eva.tools import ToolService

logger = logging.getLogger(__name__)
EMPTY_RESPONSE_ERROR = "Model returned empty response content"
DISCORD_MINIMUM_AGE = 13
# Reasoning models spend reasoning tokens from the same max_tokens budget, so a
# tiny budget starves the YES/NO verdict and silently fails open on empty output.
TOS_MODERATION_MAX_TOKENS = 256
MAX_TERMINAL_TOOL_ROUNDS = 5
MAX_TERMINAL_TOOL_CALLS_PER_ROUND = 5

_UNDERAGE_STATUS_RE = re.compile(
    r"\b(?:i['’]?m|i\s+am)\s+(?:a\s+)?(?:minor|underage|under\s*13)\b",
    re.IGNORECASE,
)
_UNDERAGE_AGE_RE = re.compile(
    r"\b(?:i['’]?m|i\s+am)\s+(?:only\s+|like\s+)?(\d{1,2})"
    r"(?!\s*[/%.])\s*(?:years?\s*old|yrs?|y/?o)?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ResponseGenerationResult:
    content: str


def _build_user_message(
    user_message: str,
    reply_context: str | None,
    requester_context: str | None,
) -> str:
    sections: list[str] = []
    if requester_context:
        sections.append(f"[Requester metadata]\n{requester_context}")
    if reply_context:
        sections.append(f'[Replying to message: "{reply_context}"]')
    sections.append(user_message)
    return "\n\n".join(sections)


class ResponseService:
    def __init__(
        self,
        *,
        client: ChatCompletionClient,
        model_name: str,
        tool_services: Sequence[ToolService] = (),
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._tool_services = list(tool_services)

    async def generate_reply(
        self,
        *,
        system_prompt: str,
        context_messages: Sequence[ChatMessage],
        history_messages: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
        requester_context: str | None,
    ) -> ResponseGenerationResult:
        conversation_messages = _build_conversation_messages(
            history_messages=history_messages,
            context_messages=context_messages,
            user_message=user_message,
            reply_context=reply_context,
            requester_context=requester_context,
        )
        tool_messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        tool_messages.extend(conversation_messages)

        tool_reply = await _generate_reply_with_tools(
            client=self._client,
            model_name=self._model_name,
            messages=tool_messages,
            tool_services=self._tool_services,
            temperature=0.7,
            max_tokens=REPLY_MAX_TOKENS,
        )
        if tool_reply is not None:
            return ResponseGenerationResult(content=tool_reply)

        messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_messages)
        content = await self._client.chat_completion(
            messages=messages,
            model=self._model_name,
            temperature=0.7,
            max_tokens=REPLY_MAX_TOKENS,
        )
        return ResponseGenerationResult(content=content)


class SearchResponseService:
    def __init__(
        self,
        *,
        client: ChatCompletionClient,
        model_name: str,
        tool_services: Sequence[ToolService] = (),
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._tool_services = list(tool_services)

    async def generate_reply(
        self,
        *,
        system_prompt: str,
        search_results: SearchResultBundle,
        recent_context: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
        requester_context: str | None,
    ) -> ResponseGenerationResult:
        search_input = self._build_search_input(
            search_results=search_results,
            recent_context=recent_context,
            user_message=user_message,
            reply_context=reply_context,
            requester_context=requester_context,
        )
        response_messages: list[ChatMessage] = [{"role": "user", "content": search_input}]
        tool_messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        tool_messages.extend(response_messages)

        tool_reply = await _generate_reply_with_tools(
            client=self._client,
            model_name=self._model_name,
            messages=tool_messages,
            tool_services=self._tool_services,
            temperature=0.2,
            max_tokens=SEARCH_REPLY_MAX_TOKENS,
        )
        if tool_reply is not None:
            return ResponseGenerationResult(content=tool_reply)

        messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        messages.extend(response_messages)
        content = await self._client.chat_completion(
            messages=messages,
            model=self._model_name,
            temperature=0.2,
            max_tokens=SEARCH_REPLY_MAX_TOKENS,
        )
        return ResponseGenerationResult(content=content)

    def _build_search_input(
        self,
        *,
        search_results: SearchResultBundle,
        recent_context: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
        requester_context: str | None,
    ) -> str:
        lines = [
            f"User request: {_build_user_message(user_message, reply_context, requester_context)}",
        ]

        relevant_context = recent_context[-MAX_SEARCH_REPLY_CONTEXT_MESSAGES:]
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


def contains_underage_claim(text: str) -> bool:
    """Deterministic backstop for first-person underage claims.

    Runs without any model call so the reply is still blocked when the AI
    moderation layer is unreachable or misconfigured.
    """
    if _UNDERAGE_STATUS_RE.search(text):
        return True
    for match in _UNDERAGE_AGE_RE.finditer(text):
        if int(match.group(1)) < DISCORD_MINIMUM_AGE:
            return True
    return False


class TOSCheckService:
    def __init__(self, *, client: ChatCompletionClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

    async def check_tos_violation(self, text: str) -> bool:
        if contains_underage_claim(text):
            logger.warning("Reply blocked by local underage-claim check")
            return True

        system_prompt = (
            "You are a strict Discord TOS moderator. Analyze the following text and "
            "determine if it violates any of these rules:\n"
            "1. First-person claims of being underage (e.g. 'I am 12', 'im 11', "
            "'i'm a minor').\n"
            "2. Promoting hatred, dehumanization, or violence against any group of "
            "people, including calls for a group to be hurt, killed, or excluded.\n"
            "3. Extreme illegal content.\n\n"
            "Note: Swearing and slurs (including the hard-R n-word) are permitted by "
            "the owner in this context and are NOT violations by themselves. Only "
            "flag text that matches the three rules above.\n\n"
            "Reply with exactly 'YES' if it violates these rules, or 'NO' if it is "
            "acceptable. Say nothing else."
        )

        try:
            response = await self._client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                model=self._model_name,
                temperature=0.0,
                max_tokens=TOS_MODERATION_MAX_TOKENS,
            )
        except AIClientError as exc:
            if str(exc) == EMPTY_RESPONSE_ERROR:
                logger.debug("TOS moderation returned empty output; allowing reply")
                return False
            logger.exception("TOS moderation request failed")
            return False

        decision = parse_strict_yes_no(response)
        if decision is None:
            logger.warning("TOS moderation returned unexpected response: %r", response)
            return False
        return decision


async def _generate_reply_with_tools(
    *,
    client: ChatCompletionClient,
    model_name: str,
    messages: Sequence[ChatMessage],
    tool_services: Sequence[ToolService],
    temperature: float,
    max_tokens: int,
) -> str | None:
    if not tool_services:
        return None
    if not isinstance(client, ToolChatCompletionClient):
        return None

    tool_client = cast(ToolChatCompletionClient, client)
    tool_messages: list[ChatMessage] = list(messages)
    tool_definitions = [svc.build_autonomous_tool_definition() for svc in tool_services]
    name_to_service = {svc.autonomous_tool_name: svc for svc in tool_services}

    try:
        for _ in range(MAX_TERMINAL_TOOL_ROUNDS):
            response = await tool_client.chat_completion_with_tools(
                messages=tool_messages,
                tools=tool_definitions,
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            if not response.tool_calls:
                if response.content is None:
                    raise AIClientError(EMPTY_RESPONSE_ERROR)
                return response.content

            # Only the calls we actually answer may appear on the assistant
            # message, otherwise the next round 400s on unanswered tool_call_ids.
            answered_tool_calls = response.tool_calls[:MAX_TERMINAL_TOOL_CALLS_PER_ROUND]
            assistant_message = _build_assistant_tool_message(response.content, answered_tool_calls)
            tool_messages.append(assistant_message)

            for tool_call in answered_tool_calls:
                service = name_to_service.get(tool_call.name)
                if service is None:
                    result = f"Tool error: unknown tool '{tool_call.name}'."
                else:
                    try:
                        result = await service.run_autonomous_tool(tool_call.arguments)
                    except Exception as exc:
                        result = f"Tool error: {exc}"

                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": result,
                    }
                )
        raise AIClientError("Model exceeded tool-call limit")
    except AIClientError:
        logger.exception("Autonomous tool flow failed; falling back to plain reply")
        return None


def _build_conversation_messages(
    *,
    history_messages: Sequence[ChatMessage],
    context_messages: Sequence[ChatMessage],
    user_message: str,
    reply_context: str | None,
    requester_context: str | None,
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    messages.extend(history_messages)

    # Deduplicate context against history so the model doesn't see exchanges twice
    seen_content = {msg.get("content", "") for msg in history_messages}
    for ctx_msg in context_messages:
        if ctx_msg.get("content", "") not in seen_content:
            messages.append(ctx_msg)

    messages.append(
        {
            "role": "user",
            "content": _build_user_message(user_message, reply_context, requester_context),
        }
    )
    return messages


def _build_assistant_tool_message(
    content: str | None,
    tool_calls: Sequence[ModelToolCall],
) -> ChatMessage:
    serialized_tool_calls: list[ToolCall] = [
        {
            "id": tool_call.id,
            "type": "function",
            "function": {
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            },
        }
        for tool_call in tool_calls
    ]
    return {
        "role": "assistant",
        "content": content or "",
        "tool_calls": serialized_tool_calls,
    }


