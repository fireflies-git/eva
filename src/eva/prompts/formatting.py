"""Formatting rules section for the system prompt."""

def build_formatting_section() -> str:
    return (
        "## Response Formatting\n"
        "1. Keep normal chat replies short by default.\n"
        "2. Use bullets for multi-part answers.\n"
        "3. Use fenced code blocks for code.\n"
        "4. Avoid meta-commentary.\n"
        "5. For factual claims about chat participants, ground the answer "
        "in the latest visible message evidence."
    )
