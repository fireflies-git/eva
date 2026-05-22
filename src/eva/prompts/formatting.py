"""Formatting rules section for the system prompt."""


def build_formatting_section() -> str:
    return (
        "## Formatting\n"
        "Discord markdown. Fenced code blocks for code or terminal output. Bullets only "
        "when you actually have a list. Skip meta-commentary."
    )
