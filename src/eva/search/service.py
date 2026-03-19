from __future__ import annotations

from eva.ai.schemas import ChatMessage
from eva.search.client import SearchClientError, SerperClient
from eva.search.detector import SearchDetector
from eva.search.query_builder import SearchQueryBuilder
from eva.search.schemas import SearchResultBundle


class SearchService:
    def __init__(
        self,
        *,
        client: SerperClient,
        detector: SearchDetector,
        query_builder: SearchQueryBuilder,
    ) -> None:
        self._client = client
        self._detector = detector
        self._query_builder = query_builder

    async def search_if_needed(
        self,
        *,
        user_message: str,
        recent_context: list[ChatMessage],
        reply_context: str | None,
    ) -> SearchResultBundle | None:
        decision = await self._detector.should_search(
            user_message,
            recent_context=recent_context,
            reply_context=reply_context,
        )
        if not decision.should_search:
            return None

        query = await self._query_builder.build_query(
            user_message=user_message,
            recent_context=recent_context,
            reply_context=reply_context,
        )
        if not query:
            raise SearchClientError("Search query could not be built")

        result = await self._client.search(query)
        if not result.has_usable_results():
            raise SearchClientError("Search returned no usable results")
        return result
