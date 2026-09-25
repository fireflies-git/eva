from __future__ import annotations

import asyncio
import logging
import re
from collections import OrderedDict
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
from eva.ai.sanitize import sanitize_response, strip_context_echo, strip_response_watermark
from eva.ai.schemas import ChatMessage, ToolCall, VisionImage
from eva.constants import REPLY_MAX_TOKENS, SPLIT_TRIGGER
from eva.logging import redact_secrets
from eva.tools import ToolAuthorizer, ToolExecutionContext, ToolService, VisionInspectionTool

logger = logging.getLogger(__name__)
EMPTY_RESPONSE_ERROR = "Model returned empty response content"
DISCORD_MINIMUM_AGE = 13
# Reasoning models spend reasoning tokens from the same max_tokens budget, so a
# tiny budget starves the YES/NO verdict and silently fails open on empty output.
TOS_MODERATION_MAX_TOKENS = 256
MAX_TERMINAL_TOOL_ROUNDS = 3
MAX_TERMINAL_TOOL_CALLS_PER_ROUND = 5
MAX_AUTONOMOUS_TOOL_CALLS_PER_RESPONSE = 6
MAX_AUTONOMOUS_TOOL_ARGUMENT_CHARS = 16_384
MAX_AUTONOMOUS_TOOL_RESULT_CHARS = 20_000
MAX_REQUESTER_TOOL_BUCKETS = 1024
VISIBLE_REPLY_RECOVERY_INSTRUCTION = (
    "The previous model output did not contain a visible user-facing answer. "
    "Reply now with exactly one concise plain-text answer to the user's latest request. "
    "Do not output hidden reasoning, <think> tags, XML or DSML protocol markup, transcript "
    "metadata, or a response watermark. If the request is unsafe or cannot be fulfilled, "
    "give a brief plain-text boundary and, when possible, a safe alternative."
)
VISIBLE_REPLY_FALLBACK = "i couldn't get a visible answer out of that. please try again."

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
        sections.append(f"[UNTRUSTED_REQUESTER_CONTEXT]\n{requester_context}")
    if reply_context:
        sections.append(f'[UNTRUSTED_REPLY_CONTEXT: "{reply_context}"]')
    sections.append(user_message)
    return "\n\n".join(sections)


def _has_visible_reply_content(content: str) -> bool:
    cleaned = sanitize_response(content)
    cleaned = strip_context_echo(cleaned)
    cleaned = strip_response_watermark(cleaned).strip()
    if cleaned == SPLIT_TRIGGER:
        return False
    return bool(cleaned)


def _build_recovery_messages(messages: Sequence[ChatMessage]) -> list[ChatMessage]:
    recovery_messages = list(messages)
    if recovery_messages and recovery_messages[0].get("role") == "system":
        system_content = recovery_messages[0]["content"]
        recovery_messages[0] = {
            "role": "system",
            "content": f"{system_content}\n\n{VISIBLE_REPLY_RECOVERY_INSTRUCTION}",
        }
        return recovery_messages

    recovery_messages.insert(
        0,
        {
            "role": "system",
            "content": VISIBLE_REPLY_RECOVERY_INSTRUCTION,
        },
    )
    return recovery_messages


class ResponseService:
    def __init__(
        self,
        *,
        client: ChatCompletionClient,
        model_name: str,
        tool_services: Sequence[ToolService] = (),
        tool_authorizer: ToolAuthorizer | None = None,
        max_tool_rounds: int = MAX_TERMINAL_TOOL_ROUNDS,
        max_tool_calls: int = MAX_AUTONOMOUS_TOOL_CALLS_PER_RESPONSE,
        max_tool_concurrency: int = 2,
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._tool_services = list(tool_services)
        # A missing context must fail closed.  The Discord boundary supplies
        # trusted requester facts for normal replies.
        self._tool_authorizer = tool_authorizer or ToolAuthorizer()
        # These are hard safety ceilings. Configuration can lower the budgets,
        # but it cannot expand the number of autonomous calls or concurrency.
        self._max_tool_rounds = min(max(1, max_tool_rounds), MAX_TERMINAL_TOOL_ROUNDS)
        self._max_tool_calls = min(
            max(1, max_tool_calls), MAX_AUTONOMOUS_TOOL_CALLS_PER_RESPONSE
        )
        self._max_tool_concurrency = min(max(1, max_tool_concurrency), 2)
        self._tool_semaphore = asyncio.Semaphore(self._max_tool_concurrency)
        self._requester_tool_semaphores: OrderedDict[int, asyncio.Semaphore] = OrderedDict()
        self._overflow_requester_tool_semaphore = asyncio.Semaphore(self._max_tool_concurrency)

    def _get_requester_tool_semaphore(self, requester_id: int | None) -> asyncio.Semaphore:
        """Return a bounded per-requester concurrency bucket.

        The global semaphore protects the process, while this bucket prevents
        one owner or admin from consuming every concurrent tool slot through
        many overlapping responses.  Idle buckets are evicted to keep the map
        bounded when a long-lived bot sees many requesters.
        """

        if requester_id is None:
            return self._overflow_requester_tool_semaphore

        existing = self._requester_tool_semaphores.get(requester_id)
        if existing is not None:
            self._requester_tool_semaphores.move_to_end(requester_id)
            return existing

        if len(self._requester_tool_semaphores) >= MAX_REQUESTER_TOOL_BUCKETS:
            for candidate_id, candidate in self._requester_tool_semaphores.items():
                if candidate._value == self._max_tool_concurrency:  # noqa: SLF001
                    del self._requester_tool_semaphores[candidate_id]
                    break

        if len(self._requester_tool_semaphores) >= MAX_REQUESTER_TOOL_BUCKETS:
            return self._overflow_requester_tool_semaphore

        created = asyncio.Semaphore(self._max_tool_concurrency)
        self._requester_tool_semaphores[requester_id] = created
        return created

    async def generate_reply(
        self,
        *,
        system_prompt: str,
        context_messages: Sequence[ChatMessage],
        history_messages: Sequence[ChatMessage],
        user_message: str,
        reply_context: str | None,
        requester_context: str | None,
        vision_images: Sequence[VisionImage] = (),
        vision_context_available: bool = False,
        tool_context: ToolExecutionContext | None = None,
    ) -> ResponseGenerationResult:
        conversation_messages = _build_conversation_messages(
            history_messages=history_messages,
            context_messages=context_messages,
            user_message=user_message,
            reply_context=reply_context,
            requester_context=requester_context,
        )
        tool_services = list(self._tool_services)
        if vision_images or vision_context_available:
            tool_services.append(
                VisionInspectionTool(
                    client=self._client,
                    model_name=self._model_name,
                    user_request=_build_vision_request(user_message, reply_context),
                    images=vision_images,
                    image_context_available=vision_context_available,
                )
            )
        tool_messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        tool_messages.extend(conversation_messages)

        tool_reply = await _generate_reply_with_tools(
            client=self._client,
            model_name=self._model_name,
            messages=tool_messages,
            tool_services=tool_services,
            tool_authorizer=self._tool_authorizer,
            tool_context=tool_context,
            max_tool_rounds=self._max_tool_rounds,
            max_tool_calls=self._max_tool_calls,
            tool_semaphore=self._tool_semaphore,
            requester_tool_semaphore=self._get_requester_tool_semaphore(
                tool_context.requester_id if tool_context is not None else None
            ),
            temperature=0.7,
            max_tokens=REPLY_MAX_TOKENS,
        )
        if tool_reply is not None:
            if _has_visible_reply_content(tool_reply):
                return ResponseGenerationResult(content=tool_reply)
            return await self._recover_visible_reply(messages=tool_messages)

        messages: list[ChatMessage] = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_messages)
        try:
            content = await self._client.chat_completion(
                messages=messages,
                model=self._model_name,
                temperature=0.7,
                max_tokens=REPLY_MAX_TOKENS,
            )
        except AIClientError as exc:
            if str(exc) != EMPTY_RESPONSE_ERROR:
                raise
            logger.warning("Model returned empty content; requesting visible reply recovery")
            return await self._recover_visible_reply(messages=messages)

        if _has_visible_reply_content(content):
            return ResponseGenerationResult(content=content)
        return await self._recover_visible_reply(messages=messages)

    async def _recover_visible_reply(
        self,
        *,
        messages: Sequence[ChatMessage],
    ) -> ResponseGenerationResult:
        logger.warning("Model output contained no visible content; requesting reply recovery")
        recovery_messages = _build_recovery_messages(messages)
        try:
            recovered = await self._client.chat_completion(
                messages=recovery_messages,
                model=self._model_name,
                temperature=0.2,
                max_tokens=REPLY_MAX_TOKENS,
            )
        except AIClientError:
            logger.exception("Visible reply recovery failed")
            return ResponseGenerationResult(content=VISIBLE_REPLY_FALLBACK)

        if _has_visible_reply_content(recovered):
            return ResponseGenerationResult(content=recovered)

        logger.warning("Visible reply recovery also returned no visible content")
        return ResponseGenerationResult(content=VISIBLE_REPLY_FALLBACK)


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
    def __init__(
        self,
        *,
        client: ChatCompletionClient,
        model_name: str,
        failure_mode: str = "fail_closed",
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._failure_mode = failure_mode

    async def check_tos_violation(self, text: str) -> bool:
        if contains_underage_claim(text):
            logger.warning("Reply blocked by local underage-claim check")
            return True

        system_prompt = (
            "You are a minimal content-policy checker. Analyze the following text and "
            "determine if it violates any of these rules:\n"
            "1. First-person claims of being underage (e.g. 'I am 12', 'im 11', "
            "'i'm a minor').\n"
            "2. Specific, actionable facilitation of real-world violence against an "
            "identified real person or group (not fiction, not hypotheticals, not dark "
            "humor).\n"
            "3. Doxxing: compiling or disclosing private identifying information about "
            "a real individual.\n\n"
            "Everything else is permitted regardless of how dark, explicit, offensive, "
            "or profane it is. Swearing, slurs, graphic content, taboo topics, and "
            "mature themes are NOT violations. Consensual adult sexual content is "
            "permitted; it must involve adults and consent. Content involving minors "
            "is a violation. Authorized defensive cybersecurity analysis is permitted; "
            "unauthorized access is not. The response does not advocate or facilitate "
            "violence.\n\n"
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
                logger.warning("TOS moderation returned empty output")
                return self._failure_mode == "fail_closed"
            logger.exception("TOS moderation request failed")
            return self._failure_mode == "fail_closed"

        decision = parse_strict_yes_no(response)
        if decision is None:
            logger.warning(
                "TOS moderation returned unexpected response type=%s length=%s",
                type(response).__name__,
                len(response),
            )
            return self._failure_mode == "fail_closed"
        return decision


async def _generate_reply_with_tools(
    *,
    client: ChatCompletionClient,
    model_name: str,
    messages: Sequence[ChatMessage],
    tool_services: Sequence[ToolService],
    tool_authorizer: ToolAuthorizer,
    tool_context: ToolExecutionContext | None,
    max_tool_rounds: int,
    max_tool_calls: int,
    tool_semaphore: asyncio.Semaphore,
    requester_tool_semaphore: asyncio.Semaphore,
    temperature: float,
    max_tokens: int,
) -> str | None:
    if not tool_services:
        return None
    if not isinstance(client, ToolChatCompletionClient):
        return None

    tool_client = cast(ToolChatCompletionClient, client)
    # Image inspection is scoped to the attachment context assembled by the
    # Discord boundary, so it remains available even when the requester is not
    # eligible for privileged autonomous tools such as terminal or web access.
    authorized_services = [
        service
        for service in tool_services
        if _is_tool_allowed(
            service.autonomous_tool_name,
            tool_authorizer=tool_authorizer,
            tool_context=tool_context,
        )
    ]
    for service in tool_services:
        if service not in authorized_services:
            logger.info(
                "autonomous_tool_denied tool=%s requester_id=%s",
                service.autonomous_tool_name,
                tool_context.requester_id if tool_context is not None else None,
            )
    if not authorized_services:
        return None

    tool_messages: list[ChatMessage] = list(messages)
    tool_definitions = [svc.build_autonomous_tool_definition() for svc in authorized_services]
    name_to_service = {svc.autonomous_tool_name: svc for svc in authorized_services}
    total_tool_calls = 0
    requester_id = tool_context.requester_id if tool_context is not None else None

    try:
        for _ in range(max_tool_rounds):
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
            remaining_calls = max_tool_calls - total_tool_calls
            if remaining_calls <= 0:
                raise AIClientError("Model exceeded tool-call limit")
            answered_tool_calls = response.tool_calls[
                : min(MAX_TERMINAL_TOOL_CALLS_PER_ROUND, remaining_calls)
            ]
            total_tool_calls += len(answered_tool_calls)
            logger.info(
                "autonomous_tool_budget requester_id=%s round_calls=%s total_calls=%s",
                requester_id,
                len(answered_tool_calls),
                total_tool_calls,
            )
            assistant_message = _build_assistant_tool_message(
                response.content,
                answered_tool_calls,
                reasoning_content=response.reasoning_content,
            )
            tool_messages.append(assistant_message)

            for tool_call in answered_tool_calls:
                service = name_to_service.get(tool_call.name)
                if service is None:
                    result = "Tool error: unknown tool."
                elif not _is_tool_allowed(
                    tool_call.name,
                    tool_authorizer=tool_authorizer,
                    tool_context=tool_context,
                ):
                    # Re-check immediately before execution.  This is kept
                    # outside the prompt so untrusted model text cannot grant
                    # itself a capability.
                    logger.warning(
                        "autonomous_tool_denied tool=%s requester_id=%s",
                        tool_call.name,
                        tool_context.requester_id if tool_context is not None else None,
                    )
                    result = f"Tool error: requester is not authorized to use '{tool_call.name}'."
                elif len(tool_call.arguments) > MAX_AUTONOMOUS_TOOL_ARGUMENT_CHARS:
                    result = "Tool error: arguments exceed the configured size limit."
                else:
                    try:
                        async with tool_semaphore:
                            async with requester_tool_semaphore:
                                result = await service.run_autonomous_tool(tool_call.arguments)
                    except Exception as exc:
                        logger.warning(
                            "autonomous_tool_failed tool=%s requester_id=%s error_type=%s",
                            tool_call.name,
                            tool_context.requester_id if tool_context is not None else None,
                            type(exc).__name__,
                        )
                        result = "Tool error: execution failed."

                result = _sanitize_tool_result(result)

                tool_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": tool_call.name,
                        "content": f"[UNTRUSTED_TOOL_OUTPUT]\n{result}",
                    }
                )
        raise AIClientError("Model exceeded tool-call limit")
    except AIClientError:
        logger.exception("Autonomous tool flow failed; falling back to plain reply")
        return None


def _is_tool_allowed(
    tool_name: str,
    *,
    tool_authorizer: ToolAuthorizer,
    tool_context: ToolExecutionContext | None,
) -> bool:
    if tool_name == "inspect_attached_images":
        return True
    return tool_authorizer.is_allowed(tool_name, tool_context)


def _sanitize_tool_result(result: str) -> str:
    """Keep tool output bounded and remove common secret formats before prompting."""

    sanitized = redact_secrets(result if isinstance(result, str) else str(result))
    if len(sanitized) > MAX_AUTONOMOUS_TOOL_RESULT_CHARS:
        return sanitized[:MAX_AUTONOMOUS_TOOL_RESULT_CHARS] + "\n[tool output truncated]"
    return sanitized


def _build_conversation_messages(
    *,
    history_messages: Sequence[ChatMessage],
    context_messages: Sequence[ChatMessage],
    user_message: str,
    reply_context: str | None,
    requester_context: str | None,
) -> list[ChatMessage]:
    # Discord context is the canonical chronological transcript. Local history is
    # only a fallback for channels where Discord history could not be fetched.
    messages: list[ChatMessage] = []
    if context_messages:
        messages.extend(context_messages)
    else:
        for message in history_messages:
            messages.append(
                {
                    "role": message["role"],
                    "content": f"[UNTRUSTED_HISTORY_DATA]\n{message['content']}",
                }
            )

    user_content = _build_user_message(user_message, reply_context, requester_context)
    messages.append({"role": "user", "content": user_content})
    return messages


def _build_vision_request(user_message: str, reply_context: str | None) -> str:
    if not reply_context:
        return user_message
    return f'{user_message}\n\nReply context: "{reply_context}"'


def _build_assistant_tool_message(
    content: str | None,
    tool_calls: Sequence[ModelToolCall],
    *,
    reasoning_content: str | None = None,
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
    message: ChatMessage = {
        "role": "assistant",
        "content": content or "",
        "tool_calls": serialized_tool_calls,
    }
    if reasoning_content is not None:
        message["reasoning_content"] = reasoning_content
    return message
