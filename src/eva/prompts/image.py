"""Prompt helpers for image detection and image request construction."""

from __future__ import annotations

_MAX_REPLY_CONTEXT_CHARS = 1_200
_REPLY_CONTEXT_HINTS: tuple[str, ...] = (
    " it",
    " this",
    " that",
    " same",
    " another version",
    " more like",
    " like this",
    " like that",
    " keep the",
    " make it",
    " make this",
    " make that",
    " turn it",
    " turn this",
    " turn that",
    " use this",
    " use that",
)
_SHORT_MODIFIER_LEADS: tuple[str, ...] = (
    "make",
    "turn",
    "change",
    "add",
    "remove",
    "use",
    "keep",
    "same",
    "more",
    "less",
    "redo",
)
_EXPLICIT_IMAGE_REQUEST_EXAMPLES = (
    "generate an image",
    "create an image",
    "make an image",
    "make me an image",
    "draw",
    "create a picture",
    "make art",
    "generate artwork",
    "make a thumbnail",
    "make a banner",
    "make a logo",
)


def build_image_decision_prompt() -> str:
    examples = ", ".join(f"'{example}'" for example in _EXPLICIT_IMAGE_REQUEST_EXAMPLES)
    return (
        "You decide whether an image should be generated in response to a message "
        "in a Discord chat.\n\n"
        "Reply with exactly YES or NO - nothing else.\n\n"
        "Reply YES only if the user explicitly requests an image, picture, photo, "
        "artwork, drawing, render, logo, wallpaper, banner, thumbnail, or other "
        "visual media to be created. Strong YES examples include: "
        f"{examples}.\n\n"
        "Reply NO if the user is asking for text-only information, explanations, "
        "code, or anything that does not clearly request an image to be produced.\n\n"
        "Be conservative. If unsure, reply NO."
    )


def build_image_generation_prompt(*, user_message: str, reply_context: str | None) -> str:
    request = user_message.strip()
    if not request:
        return ""
    if not reply_context:
        return request
    if not _requires_reply_context(request):
        return request

    clipped_reply_context = reply_context.strip()[:_MAX_REPLY_CONTEXT_CHARS]
    return (
        "Create an image using the referenced content as the subject or base concept.\n\n"
        f"Referenced content:\n{clipped_reply_context}\n\n"
        f"Requested changes or style:\n{request}"
    )


def _requires_reply_context(request: str) -> bool:
    normalized = " ".join(request.lower().split())
    padded = f" {normalized}"
    if any(hint in padded for hint in _REPLY_CONTEXT_HINTS):
        return True

    words = normalized.split()
    if not words:
        return False
    return len(words) <= 12 and words[0] in _SHORT_MODIFIER_LEADS
