from __future__ import annotations

import random

from eva.constants import DISCORD_MESSAGE_LIMIT, LOADING_MESSAGES


def build_loading_text(original_content: str) -> str:
    loading = random.choice(LOADING_MESSAGES)
    return f"-# > {original_content}\n {loading}"


def build_response_text(
    original_content: str,
    reply_content: str,
    *,
    message_limit: int = DISCORD_MESSAGE_LIMIT,
) -> str:
    prefix = "-# > "
    separator = "\n "

    safe_original = original_content
    max_original_len = message_limit - len(prefix) - len(separator) - 1
    if max_original_len < 0:
        max_original_len = 0
    if len(safe_original) > max_original_len:
        if max_original_len > 3:
            safe_original = safe_original[: max_original_len - 3] + "..."
        else:
            safe_original = ""

    base = f"{prefix}{safe_original}{separator}"
    remaining = message_limit - len(base)
    if remaining <= 0:
        return base[:message_limit]

    safe_reply = reply_content
    if len(safe_reply) > remaining:
        safe_reply = safe_reply[: remaining - 3] + "..." if remaining > 3 else ""

    return f"{base}{safe_reply}"
