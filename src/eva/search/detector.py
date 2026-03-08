from __future__ import annotations

import re
from dataclasses import dataclass

LOOKUP_HINTS = (
    "search ",
    "search for",
    "look up",
    "google ",
    "find ",
    "check ",
)
RECENCY_HINTS = (
    "latest",
    "today",
    "current",
    "recent",
    "right now",
    " rn",
    " rn?",
    "this week",
    "news",
    "update",
)
EXTERNAL_FACT_HINTS = (
    "stock price",
    "share price",
    "price of",
    "market cap",
    "release date",
    "version",
    "ceo",
    "founder",
    "headquarters",
    "website",
    "docs",
    "documentation",
)
WORLD_SUPERLATIVE_PATTERN = re.compile(
    r"\b(who|what)\b.*\b(oldest|youngest|richest|largest|biggest|fastest|tallest)\b.*\b"
    r"(world|alive|living)\b"
)
PERSON_SUPERLATIVE_PATTERN = re.compile(
    r"\bwho\b.*\b(oldest|youngest|richest|largest|biggest|fastest|tallest)\b.*\b"
    r"(person|human|man|woman|player|athlete|president|ceo)\b"
)
NEGATIVE_HINTS = (
    "last message",
    "who said",
    "summarize last",
    "in this server",
    "in this chat",
    "in this channel",
    "thank him",
    "write ",
    "poem",
    "joke",
    "story",
)
REFERENTIAL_LOOKUP_PATTERN = re.compile(
    r"\b(what(?:'s| is)?|who(?:'s| is)?|when(?:'s| is)?|where(?:'s| is)?)\b.*\b("
    r"ceo|founder|owner|price|stock|release|version|website|docs|documentation|news"
    r")\b"
)


@dataclass(frozen=True, slots=True)
class SearchDecision:
    should_search: bool
    reason: str = ""


class SearchDetector:
    def should_search(self, user_message: str) -> SearchDecision:
        text = user_message.strip().lower()
        if not text:
            return SearchDecision(should_search=False)
        if any(hint in text for hint in NEGATIVE_HINTS):
            return SearchDecision(should_search=False)
        if any(hint in text for hint in RECENCY_HINTS):
            return SearchDecision(should_search=True, reason="recency")
        if any(hint in text for hint in EXTERNAL_FACT_HINTS):
            return SearchDecision(should_search=True, reason="external-fact")
        if WORLD_SUPERLATIVE_PATTERN.search(text):
            return SearchDecision(should_search=True, reason="world-superlative")
        if PERSON_SUPERLATIVE_PATTERN.search(text):
            return SearchDecision(should_search=True, reason="person-superlative")
        if any(hint in text for hint in LOOKUP_HINTS):
            return SearchDecision(should_search=True, reason="lookup")
        if REFERENTIAL_LOOKUP_PATTERN.search(text):
            return SearchDecision(should_search=True, reason="entity-lookup")
        return SearchDecision(should_search=False)
