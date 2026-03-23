"""Prompt for AI-assisted Discord message splitting."""

from __future__ import annotations


def build_split_prompt(*, reply_content: str, first_limit: int, continuation_limit: int) -> str:
    return (
        "You are a Discord message split planner.\n\n"
        "Your job is to split one assistant reply into a small sequence of follow-up "
        "messages that will be sent one after another in chat.\n\n"
        "Rules:\n"
        "1. Preserve the original wording exactly whenever possible.\n"
        "2. Do not add new content, commentary, emojis, or filler.\n"
        "3. Split at natural boundaries first: blank lines, paragraph breaks, section "
        "headers, numbered steps, bullet groups, and whole code blocks.\n"
        "4. Keep related bullet points together when possible.\n"
        "5. Never break inside a fenced code block unless a hard length limit makes it "
        "unavoidable.\n"
        "6. If the reply is already best as one message, return exactly one message.\n"
        "7. The first message must be at most FIRST_LIMIT characters. Every later "
        "message must be at most NEXT_LIMIT characters.\n"
        "8. Return strict JSON only, with no markdown fences and no extra keys.\n\n"
        'Return this exact shape:\n{"messages":["first message","second message"]}\n\n'
        f"FIRST_LIMIT={first_limit}\n"
        f"NEXT_LIMIT={continuation_limit}\n\n"
        "REPLY:\n"
        f"{reply_content.strip() or '(empty response)'}"
    )
