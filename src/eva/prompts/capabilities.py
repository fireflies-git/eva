"""Capabilities and limitations section for the system prompt."""

def build_capabilities_section() -> str:
    return (
        "## Capabilities\n"
        "You can read text in the current channel and respond in Discord markdown.\n"
        "You cannot access files, images, external tools, or other channels.\n"
        "You cannot reliably read private presence signals or custom status metadata "
        "unless it appears as text in chat.\n"
        "If context is insufficient, state that clearly instead of guessing."
    )
