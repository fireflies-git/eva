"""Autonomous image-inspection tool for the response agent."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Sequence
from typing import Any

from eva.ai.client import AIClientError, ChatCompletionClient
from eva.ai.schemas import ChatMessage, ContentPart, VisionImage

logger = logging.getLogger(__name__)

_AUTONOMOUS_TOOL_NAME = "inspect_attached_images"
_MAX_FOCUS_CHARS = 1_000
_VISION_MAX_TOKENS = 1_024

_VISION_SYSTEM_PROMPT = (
    "You are Eva's image-inspection sub-agent. Inspect only the attached image data and "
    "the user's request. Return concise, factual findings for the parent assistant. "
    "Read visible text when relevant, describe visual evidence when asked, and say when "
    "something is unclear or unreadable. Never invent details that are not visible. "
    "Do not address the user directly and do not include a response watermark."
)


class VisionInspectionTool:
    """Inspect the images selected for one response through a separate model pass."""

    def __init__(
        self,
        *,
        client: ChatCompletionClient,
        model_name: str,
        user_request: str,
        images: Sequence[VisionImage],
        image_context_available: bool,
    ) -> None:
        self._client = client
        self._model_name = model_name
        self._user_request = user_request.strip() or "No specific visual question was provided."
        self._images = tuple(images)
        self._image_context_available = image_context_available or bool(self._images)

    @property
    def autonomous_tool_name(self) -> str:
        return _AUTONOMOUS_TOOL_NAME

    def build_autonomous_tool_definition(self) -> dict[str, object]:
        available_images = self._format_available_images()
        if self._images:
            availability = f"Available readable images: {available_images}."
        elif self._image_context_available:
            availability = (
                "Image attachment metadata is present, but no readable supported image "
                "bytes are currently available."
            )
        else:
            availability = "No image attachment context is currently available."

        return {
            "type": "function",
            "function": {
                "name": _AUTONOMOUS_TOOL_NAME,
                "description": (
                    "Inspect currently available Discord image attachments when visual "
                    "evidence is needed to answer the user. Decide independently whether "
                    "to use this tool; do not call it for ordinary text-only requests. "
                    f"{availability}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "image_indexes": {
                            "type": "array",
                            "items": {"type": "integer", "minimum": 0},
                            "description": (
                                "Optional zero-based indexes of the images to inspect. "
                                "Omit this field to inspect every available image."
                            ),
                        },
                        "focus": {
                            "type": "string",
                            "description": (
                                "Optional short focus for the inspection, such as OCR, "
                                "chart values, or identifying an object."
                            ),
                        },
                    },
                    "additionalProperties": False,
                },
            },
        }

    async def run_autonomous_tool(self, arguments: str) -> str:
        try:
            parsed = _parse_tool_arguments(arguments)
        except ValueError as exc:
            return f"Image inspection tool error: {exc}"

        if not self._image_context_available:
            return "No image attachment context is available for inspection."
        if not self._images:
            return (
                "Image attachment metadata was present, but no readable supported image "
                "bytes are available. Do not infer visual details."
            )

        try:
            selected_images = _select_images(self._images, parsed.get("image_indexes"))
        except ValueError as exc:
            return f"Image inspection tool error: {exc}"

        focus = parsed.get("focus")
        if not isinstance(focus, str):
            focus = ""
        focus = focus.strip()[:_MAX_FOCUS_CHARS]

        return await self._inspect_images(selected_images, focus=focus)

    async def _inspect_images(
        self,
        images: Sequence[VisionImage],
        *,
        focus: str,
    ) -> str:
        request_lines = [f"User request: {self._user_request}"]
        if focus:
            request_lines.append(f"Inspection focus: {focus}")
        request_lines.append(
            "Inspect the attached image(s) and return only the findings the parent assistant "
            "needs to answer the user."
        )

        content: list[ContentPart] = [
            {"type": "text", "text": "\n".join(request_lines)},
        ]
        for image in images:
            encoded = base64.b64encode(image.data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.mime_type};base64,{encoded}",
                    },
                }
            )

        messages: list[ChatMessage] = [
            {"role": "system", "content": _VISION_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        try:
            result = await self._client.chat_completion(
                messages=messages,
                model=self._model_name,
                temperature=0.2,
                max_tokens=_VISION_MAX_TOKENS,
            )
        except AIClientError as exc:
            logger.warning("Vision inspection model call failed: %s", exc)
            return f"Image inspection failed: {exc}"
        except Exception as exc:
            logger.exception("Unexpected vision inspection failure")
            return f"Image inspection failed: {exc}"

        if not result.strip():
            return "Image inspection returned no readable findings."
        return f"Image inspection findings:\n{result.strip()}"

    def _format_available_images(self) -> str:
        return ", ".join(
            f"{index}: {image.filename} (message {image.message_id})"
            for index, image in enumerate(self._images)
        )


def _parse_tool_arguments(arguments: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments)
    except json.JSONDecodeError as exc:
        raise ValueError("arguments must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("arguments must be a JSON object")
    return parsed


def _select_images(
    images: Sequence[VisionImage],
    raw_indexes: object,
) -> tuple[VisionImage, ...]:
    if raw_indexes is None:
        return tuple(images)
    if not isinstance(raw_indexes, list) or not raw_indexes:
        raise ValueError("image_indexes must be a non-empty array when provided")

    selected: list[VisionImage] = []
    seen: set[int] = set()
    for raw_index in raw_indexes:
        if isinstance(raw_index, bool) or not isinstance(raw_index, int):
            raise ValueError("image_indexes must contain only integers")
        if raw_index < 0 or raw_index >= len(images):
            raise ValueError(f"image index {raw_index} is out of range")
        if raw_index in seen:
            continue
        seen.add(raw_index)
        selected.append(images[raw_index])
    return tuple(selected)
