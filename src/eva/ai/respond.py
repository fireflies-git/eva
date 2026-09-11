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
from eva.ai.sanitize import sanitize_response, strip_context_echo, strip_response_watermark
from eva.ai.schemas import ChatMessage, ToolCall, VisionImage
from eva.constants import REPLY_MAX_TOKENS, SPLIT_TRIGGER
from eva.tools import ToolService, VisionInspectionTool

logger = logging.getLogger(__name__)
EMPTY_RESPONSE_ERROR = "Model returned empty response content"
DISCORD_MINIMUM_AGE = 13
# Reasoning models spend reasoning tokens from the same max_tokens budget, so a
# tiny budget starves the YES/NO verdict and silently fails open on empty output.
TOS_MODERATION_MAX_TOKENS = 256
MAX_TERMINAL_TOOL_ROUNDS = 5
MAX_TERMINAL_TOOL_CALLS_PER_ROUND = 5
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
        sections.append(f"[Current requester]\n{requester_context}")
    if reply_context:
        sections.append(f'[Replying to message: "{reply_context}"]')
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
        vision_images: Sequence[VisionImage] = (),
        vision_context_available: bool = False,
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
    def __init__(self, *, client: ChatCompletionClient, model_name: str) -> None:
        self._client = client
        self._model_name = model_name

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
            "mature themes are NOT violations.\n\n"
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
            assistant_message = _build_assistant_tool_message(
                response.content,
                answered_tool_calls,
                reasoning_content=response.reasoning_content,
            )
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
    # Discord context is the canonical chronological transcript. Local history is
    # only a fallback for channels where Discord history could not be fetched.
    messages: list[ChatMessage] = list(context_messages or history_messages)

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
