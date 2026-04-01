from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

from eva.ai.client import (
    AIClientError,
    ChatCompletionClient,
    ModelToolCall,
    ResponsesClient,
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
from eva.terminal import TerminalClientError, TerminalCommandRejectedError, TerminalService

logger = logging.getLogger(__name__)
EMPTY_RESPONSE_ERROR = "Model returned empty response content"
TOS_MODERATION_MODEL = "llama3.3-70b-instruct"
MAX_TERMINAL_TOOL_ROUNDS = 3
MAX_TERMINAL_TOOL_CALLS_PER_ROUND = 3


@dataclass(frozen=True, slots=True)
class ResponseGenerationResult:
    content: str
    response_id: str | None = None


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
        terminal_service: TerminalService | None = None,
        autonomous_terminal_access: bool = False,
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._terminal_service = terminal_service
        self._autonomous_terminal_access = autonomous_terminal_access

    async def generate_reply(
        self,
        *,
        system_prompt: str,
        context_messages: Sequence[ChatMessage],
        history_messages: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
        requester_context: str | None,
        previous_response_id: str | None = None,
    ) -> ResponseGenerationResult:
        reseed_messages = _build_conversation_messages(
            history_messages=history_messages,
            context_messages=context_messages,
            user_message=user_message,
            reply_context=reply_context,
            requester_context=requester_context,
            include_history=True,
        )
        response_messages = _build_conversation_messages(
            history_messages=history_messages,
            context_messages=context_messages,
            user_message=user_message,
            reply_context=reply_context,
            requester_context=requester_context,
            include_history=previous_response_id is None,
        )
        tool_messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        tool_messages.extend(response_messages)

        tool_reply = await _generate_reply_with_terminal_tool(
            client=self._client,
            model_name=self._model_name,
            messages=tool_messages,
            terminal_service=self._terminal_service,
            autonomous_terminal_access=self._autonomous_terminal_access,
            temperature=0.7,
            max_tokens=REPLY_MAX_TOKENS,
        )
        if tool_reply is not None:
            return ResponseGenerationResult(content=tool_reply)

        if isinstance(self._client, ResponsesClient):
            return await _create_stored_response(
                client=self._client,
                instructions=system_prompt,
                initial_messages=response_messages,
                reseed_messages=reseed_messages,
                model_name=self._model_name,
                temperature=0.7,
                max_output_tokens=REPLY_MAX_TOKENS,
                previous_response_id=previous_response_id,
            )

        fallback_messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        fallback_messages.extend(reseed_messages)
        content = await self._client.chat_completion(
            messages=fallback_messages,
            model=self._model_name,
            temperature=0.7,
            max_tokens=REPLY_MAX_TOKENS,
            allow_reasoning_fallback=True,
        )
        return ResponseGenerationResult(content=content)


class SearchResponseService:
    def __init__(
        self,
        *,
        client: ChatCompletionClient,
        model_name: str,
        terminal_service: TerminalService | None = None,
        autonomous_terminal_access: bool = False,
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._terminal_service = terminal_service
        self._autonomous_terminal_access = autonomous_terminal_access

    async def generate_reply(
        self,
        *,
        system_prompt: str,
        search_results: SearchResultBundle,
        recent_context: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
        requester_context: str | None,
        previous_response_id: str | None = None,
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

        tool_reply = await _generate_reply_with_terminal_tool(
            client=self._client,
            model_name=self._model_name,
            messages=tool_messages,
            terminal_service=self._terminal_service,
            autonomous_terminal_access=self._autonomous_terminal_access,
            temperature=0.2,
            max_tokens=SEARCH_REPLY_MAX_TOKENS,
        )
        if tool_reply is not None:
            return ResponseGenerationResult(content=tool_reply)

        if isinstance(self._client, ResponsesClient):
            return await _create_stored_response(
                client=self._client,
                instructions=system_prompt,
                initial_messages=response_messages,
                reseed_messages=response_messages,
                model_name=self._model_name,
                temperature=0.2,
                max_output_tokens=SEARCH_REPLY_MAX_TOKENS,
                previous_response_id=previous_response_id,
            )

        fallback_messages: list[ChatMessage] = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": search_input,
            },
        ]
        content = await self._client.chat_completion(
            messages=fallback_messages,
            model=self._model_name,
            temperature=0.2,
            max_tokens=SEARCH_REPLY_MAX_TOKENS,
            allow_reasoning_fallback=True,
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


class TOSCheckService:
    def __init__(self, *, client: ChatCompletionClient) -> None:
        self._client = client

    async def check_tos_violation(self, text: str) -> bool:
        system_prompt = (
            "You are a strict Discord TOS moderator. Analyze the following text and "
            "determine if it violates Discord's Terms of Service, "
            "specifically checking for:\n"
            "1. Claims of being underage (e.g. 'I am 12', 'im 11', etc.)\n"
            "2. The hard-R n-word.\n"
            "3. Extreme hate speech or illegal content.\n\n"
            "Note: General swearing and mild slurs (like 'faggot' or 'retard') are "
            "permitted by the owner in this context. "
            "Only flag strict TOS violations like underage claims, the hard-R n-word, "
            "or extreme illegal/harmful content.\n\n"
            "Reply with exactly 'YES' if it violates these rules, or 'NO' if it is "
            "acceptable. Say nothing else."
        )

        try:
            response = await self._client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                model=TOS_MODERATION_MODEL,
                temperature=0.0,
                max_tokens=10,
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


async def _generate_reply_with_terminal_tool(
    *,
    client: ChatCompletionClient,
    model_name: str,
    messages: Sequence[ChatMessage],
    terminal_service: TerminalService | None,
    autonomous_terminal_access: bool,
    temperature: float,
    max_tokens: int,
) -> str | None:
    if terminal_service is None or not autonomous_terminal_access:
        return None
    if not isinstance(client, ToolChatCompletionClient):
        return None

    tool_client = cast(ToolChatCompletionClient, client)
    tool_messages: list[ChatMessage] = list(messages)
    tool_definition = terminal_service.build_autonomous_tool_definition()

    try:
        for _ in range(MAX_TERMINAL_TOOL_ROUNDS):
            response = await tool_client.chat_completion_with_tools(
                messages=tool_messages,
                tools=[tool_definition],
                model=model_name,
                temperature=temperature,
                max_tokens=max_tokens,
                allow_reasoning_fallback=True,
            )

            if not response.tool_calls:
                if response.content is None:
                    raise AIClientError(EMPTY_RESPONSE_ERROR)
                return response.content

            assistant_message = _build_assistant_tool_message(response.content, response.tool_calls)
            tool_messages.append(assistant_message)

            for tool_call in response.tool_calls[:MAX_TERMINAL_TOOL_CALLS_PER_ROUND]:
                tool_messages.append(
                    await _execute_terminal_tool_call(
                        terminal_service=terminal_service, tool_call=tool_call
                    )
                )
        raise AIClientError("Model exceeded terminal tool-call limit")
    except AIClientError:
        logger.exception("Autonomous terminal tool flow failed; falling back to plain reply")
        return None


def _build_conversation_messages(
    *,
    history_messages: Sequence[ChatMessage],
    context_messages: Sequence[ChatMessage],
    user_message: str,
    reply_context: str | None,
    requester_context: str | None,
    include_history: bool,
) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    if include_history:
        messages.extend(history_messages)
    messages.extend(context_messages)
    messages.append(
        {
            "role": "user",
            "content": _build_user_message(user_message, reply_context, requester_context),
        }
    )
    return messages


async def _create_stored_response(
    *,
    client: ResponsesClient,
    instructions: str,
    initial_messages: Sequence[ChatMessage],
    reseed_messages: Sequence[ChatMessage],
    model_name: str,
    temperature: float,
    max_output_tokens: int,
    previous_response_id: str | None,
) -> ResponseGenerationResult:
    try:
        output = await client.create_response(
            instructions=instructions,
            messages=initial_messages,
            model=model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            previous_response_id=previous_response_id,
            allow_reasoning_fallback=True,
        )
    except AIClientError as exc:
        if previous_response_id is None or not _should_retry_without_previous_response_id(exc):
            raise

        logger.warning("Responses API rejected previous response id; reseeding channel history")
        output = await client.create_response(
            instructions=instructions,
            messages=reseed_messages,
            model=model_name,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            previous_response_id=None,
            allow_reasoning_fallback=True,
        )

    return ResponseGenerationResult(content=output.content, response_id=output.response_id)


def _should_retry_without_previous_response_id(exc: AIClientError) -> bool:
    message = str(exc).lower()
    return "previous_response_id" in message or "previous response" in message


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


async def _execute_terminal_tool_call(
    *,
    terminal_service: TerminalService,
    tool_call: ModelToolCall,
) -> ChatMessage:
    if tool_call.name != terminal_service.autonomous_tool_name:
        result = f"Tool error: unknown tool '{tool_call.name}'."
    else:
        try:
            result = await terminal_service.run_autonomous_tool(tool_call.arguments)
        except TerminalCommandRejectedError as exc:
            result = f"Tool error: {exc}"
        except TerminalClientError as exc:
            result = f"Tool error: {exc}"

    return {
        "role": "tool",
        "tool_call_id": tool_call.id,
        "name": tool_call.name,
        "content": result,
    }
