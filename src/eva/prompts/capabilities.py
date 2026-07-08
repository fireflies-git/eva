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
            "You can help change your Discord display name, bio, presence, and custom "
            "status only through Eva's confirmation flow. "
            "You don't have shell or network access in this conversation, so don't pretend "
            "you do — answer from what's already in the chat."
        )

    return (
        "## What you can do\n"
        "You have a real shell inside leah's Docker container via the "
        "`run_terminal_command` tool. It's unrestricted — `curl`, `ping`, pipes, redirects, "
        "command chains, anything. Use it whenever it would actually help: pinging or "
        "curling servers, reading files/logs/configs/git state, running a quick one-liner "
        "instead of guessing. Don't ask permission, just call the tool. Chain another if "
        "the first didn't answer it. When you reply: give the answer, not a play-by-play "
        "of what you ran. Mention the command only if leah asked for it. You can also help "
        "change your Discord display name, bio, presence, and custom status only through "
        "Eva's confirmation flow."
    )
