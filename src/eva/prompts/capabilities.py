"""Capabilities section for the system prompt."""

from __future__ import annotations

from collections.abc import Collection

from eva.constants import (
    TOOL_FETCH_WEB_PAGE,
    TOOL_INSPECT_ATTACHED_IMAGES,
    TOOL_LOOKUP_DOCUMENTATION,
    TOOL_RUN_TERMINAL_COMMAND,
    TOOL_WEB_SEARCH,
)

_NO_TOOLS_SECTION = (
    "## What you can do\n"
    "You can read this channel and reply in Discord markdown. "
    "You can't check live information, browse, or run commands in this conversation. "
    "For anything current or version-specific, say you can't check instead of guessing, "
    "and don't pretend you did."
)

_TOOL_SELECTION_LINES: tuple[tuple[str, str], ...] = (
    (TOOL_WEB_SEARCH, "`web_search` finds pages and facts."),
    (
        TOOL_FETCH_WEB_PAGE,
        "`fetch_web_page` reads a URL from a search result or from the user.",
    ),
    (
        TOOL_LOOKUP_DOCUMENTATION,
        "`lookup_documentation` answers questions about a named library's API.",
    ),
    (
        TOOL_RUN_TERMINAL_COMMAND,
        "`run_terminal_command` inspects the host read-only (logs, files, git state); "
        "it is allowlisted, so don't try installers or network access.",
    ),
)

_EXTERNAL_TOOL_NAMES = frozenset(
    {
        TOOL_RUN_TERMINAL_COMMAND,
        TOOL_FETCH_WEB_PAGE,
        TOOL_LOOKUP_DOCUMENTATION,
        TOOL_WEB_SEARCH,
    }
)

_TOOL_POLICY = (
    "Use tools for anything current or version-specific: prices, news, \"latest\", exact "
    "library signatures. Don't use them for banter, opinions, or things already in the chat."
)

_RESULT_POLICY = (
    "A result starting with \"Error:\" or \"Tool error:\" is a failure: say so briefly, "
    "never invent the result, and never retry with identical arguments. "
    "Your budget is small: about 3 rounds with up to 5 calls per round, and calls in a round "
    "run in parallel, so prefer one good query over several vague ones. "
    "After a result, answer in your normal voice instead of pasting raw output. "
    "Cite at most one or two source links, only when the user would want to verify, "
    "wrapped in <> so they don't embed. "
    "Tool calls are internal: never print tool-call syntax, XML, or raw arguments in a reply."
)

_VISION_POLICY = (
    "If the current message has images, call `inspect_attached_images` before describing "
    "them, and don't claim details the tool didn't return."
)


def build_capabilities_section(*, available_tools: Collection[str]) -> str:
    """Describe only the tools offered to this requester for this message."""
    tools = frozenset(available_tools)
    has_external_tools = bool(tools & _EXTERNAL_TOOL_NAMES)
    has_vision = TOOL_INSPECT_ATTACHED_IMAGES in tools

    if not has_external_tools and not has_vision:
        return _NO_TOOLS_SECTION

    parts = ["## What you can do"]
    if has_external_tools:
        parts.append(_TOOL_POLICY)
        selection = [line for name, line in _TOOL_SELECTION_LINES if name in tools]
        parts.append("Pick the right one: " + " ".join(selection))
        parts.append(_RESULT_POLICY)
    else:
        parts.append(
            "You can't check live information or run commands in this conversation; "
            "say so instead of guessing."
        )
    if has_vision:
        parts.append(_VISION_POLICY)
    return " ".join(parts)
