from __future__ import annotations

from typing import Any

import aiohttp

from eva.search.schemas import (
    SearchAnswerBox,
    SearchKnowledgeGraph,
    SearchOrganicResult,
    SearchResultBundle,
)


class SearchClientError(RuntimeError):
    pass


class SerperClient:
    def __init__(self, *, api_key: str, timeout_seconds: float) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._session: aiohttp.ClientSession | None = None

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._timeout_seconds)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def search(self, query: str) -> SearchResultBundle:
        data = await self._request(query)
        return SearchResultBundle(
            query=query,
            answer_box=self._build_answer_box(data),
            knowledge_graph=self._build_knowledge_graph(data),
            organic_results=self._build_organic_results(data),
        )

    async def _request(self, query: str) -> dict[str, Any]:
        if self._session is None:
            raise SearchClientError("Search client is not started")

        headers = {
            "X-API-KEY": self._api_key,
            "Content-Type": "application/json",
        }

        try:
            async with self._session.post(
                "https://google.serper.dev/search",
                headers=headers,
                json={"q": query},
            ) as response:
                text = await response.text()
                if response.status != 200:
                    raise SearchClientError(
                        f"Search API error HTTP {response.status}: {text[:300]}"
                    )
                try:
                    data = await response.json()
                except Exception as exc:
                    raise SearchClientError(f"Invalid search JSON response: {text[:300]}") from exc
                if not isinstance(data, dict):
                    raise SearchClientError("Invalid search API response type")
                return data
        except TimeoutError as exc:
            raise SearchClientError("Search API request timed out") from exc
        except aiohttp.ClientError as exc:
            raise SearchClientError(f"Search API network error: {exc}") from exc

    def _build_answer_box(self, data: dict[str, Any]) -> SearchAnswerBox | None:
        raw = data.get("answerBox")
        if not isinstance(raw, dict):
            return None

        title = self._string_or_none(raw.get("title"))
        answer = self._string_or_none(raw.get("answer")) or self._string_or_none(raw.get("snippet"))
        link = self._string_or_none(raw.get("link"))
        if not title or not answer:
            return None
        return SearchAnswerBox(title=title, answer=answer, link=link)

    def _build_knowledge_graph(self, data: dict[str, Any]) -> SearchKnowledgeGraph | None:
        raw = data.get("knowledgeGraph")
        if not isinstance(raw, dict):
            return None

        title = self._string_or_none(raw.get("title"))
        description = self._string_or_none(raw.get("description"))
        source = self._string_or_none(raw.get("descriptionSource"))
        source_link = self._string_or_none(raw.get("descriptionLink"))
        if not title or not description:
            return None
        return SearchKnowledgeGraph(
            title=title,
            description=description,
            source=source,
            source_link=source_link,
        )

    def _build_organic_results(self, data: dict[str, Any]) -> list[SearchOrganicResult]:
        raw_results = data.get("organic")
        if not isinstance(raw_results, list):
            return []

        organic_results: list[SearchOrganicResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            title = self._string_or_none(item.get("title"))
            link = self._string_or_none(item.get("link"))
            snippet = self._string_or_none(item.get("snippet"))
            position = item.get("position")
            date = self._string_or_none(item.get("date"))
            if not title or not link or not snippet or not isinstance(position, int):
                continue
            organic_results.append(
                SearchOrganicResult(
                    title=title,
                    link=link,
                    snippet=snippet,
                    position=position,
                    date=date,
                )
            )
        return organic_results

    def _string_or_none(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None
