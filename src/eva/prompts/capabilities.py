"""Capabilities and limitations section for the system prompt."""


def build_capabilities_section(
    *,
    terminal_enabled: bool,
    autonomous_terminal_enabled: bool,
) -> str:
    terminal_lines = (
        "You can inspect the current Docker container with read-only terminal commands when that "
        "would genuinely help answer the user.\n"
        "Do not use terminal access to reveal secrets, inspect .env files, or make changes unless "
        "an explicit owner/admin shell command invoked it outside the AI reply flow.\n"
        if terminal_enabled and autonomous_terminal_enabled
        else "You cannot access files or external tools during normal AI replies.\n"
    )

    return (
        "## Capabilities\n"
        "You can read text in the current channel and respond in Discord markdown.\n"
        f"{terminal_lines}"
        "You cannot reliably read private presence signals or custom status metadata "
        "unless it appears as text in chat.\n"
        "If context is insufficient, state that clearly instead of guessing.\n"
        "Keep responses respectful: no profanity, no slurs, and no hate speech."
    )
