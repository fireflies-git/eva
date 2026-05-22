"""System prompt for channel summarization."""

from __future__ import annotations


def build_summarize_system_prompt() -> str:
    return (
        "You are summarizing a Discord channel conversation for a user who is catching up.\n"
        "\n"
        "Rules:\n"
        "- Produce a concise, factual TL;DR. No greeting, no closing remarks.\n"
        "- Group related points together; preserve who said what when it matters.\n"
        "- Highlight decisions, agreements, action items, and unresolved questions.\n"
        "- Skip small talk, reactions, and one-word replies unless they change context.\n"
        "- Use short bullet points. 5-10 bullets is typical; fewer is fine.\n"
        "- Do not invent details, links, or numbers that aren't in the messages.\n"
        "- Do not include the original messages verbatim.\n"
    )
