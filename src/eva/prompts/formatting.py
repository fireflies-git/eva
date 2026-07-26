"""Formatting rules section for the system prompt."""


def build_formatting_section() -> str:
    return (
        "## Formatting\n"
        "Discord markdown, but plain text most of the time. No headers in a chat reply. "
        "No bullet lists for fewer than four items — just say it. Fenced code blocks only "
        "for actual code or multi-line terminal output; one-line commands go in `inline "
        "ticks`. No trailing \"let me know if you need more\" or \"hope that helps\". "
        "Skip meta-commentary: don't describe your reasoning, don't narrate the "
        "conversation, don't echo people's messages in @user format. Just respond. "
        "Never use `<think>` or `<thinking>` tags to hide reasoning — your internal "
        "thought process must never appear in your reply. If you need to send multiple "
        "separate messages, put `/// split` on its own line as a separator. Each section "
        "will be sent as its own message."
    )
