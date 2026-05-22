"""Capabilities section for the system prompt."""


def build_capabilities_section(
    *,
    terminal_enabled: bool,
    autonomous_terminal_enabled: bool,
) -> str:
    if not (terminal_enabled and autonomous_terminal_enabled):
        return (
            "## What you can do\n"
            "You can read this channel and reply in Discord markdown. "
            "You don't have shell or network access in this conversation, so don't pretend "
            "you do — answer from what's already in the chat."
        )

    return (
        "## What you can do\n"
        "You have a real shell inside leah's Docker container via the "
        "`run_terminal_command` tool. It's unrestricted — `curl`, `ping`, pipes, redirects, "
        "command chains, anything. Use it whenever it would actually help:\n"
        "- pinging or curling servers to see if they're up\n"
        "- reading files, logs, configs, git state\n"
        "- running a quick one-liner so you can answer accurately instead of guessing\n"
        "Don't ask permission, just call the tool. If the first command doesn't answer the "
        "question, chain another. Treat it like your own shell."
    )
