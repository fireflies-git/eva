from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SearchAnswerBox:
    title: str
    answer: str
    link: str | None = None


@dataclass(frozen=True, slots=True)
class SearchKnowledgeGraph:
    title: str
    description: str
    source: str | None = None
    source_link: str | None = None


@dataclass(frozen=True, slots=True)
class SearchOrganicResult:
    title: str
    link: str
    snippet: str
    position: int
    date: str | None = None


@dataclass(frozen=True, slots=True)
class SearchResultBundle:
    query: str
    answer_box: SearchAnswerBox | None = None
    knowledge_graph: SearchKnowledgeGraph | None = None
    organic_results: list[SearchOrganicResult] = field(default_factory=list)
    is_error: bool = False

    def has_usable_results(self) -> bool:
        return (
            self.answer_box is not None
            or self.knowledge_graph is not None
            or bool(self.organic_results)
        )

    @classmethod
    def error(cls) -> SearchResultBundle:
        return cls(query="", is_error=True)
