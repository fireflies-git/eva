import asyncio
from typing import cast

import discord

from eva.ai.orchestrator import (
    IMAGE_FAILURE_MESSAGE,
    SEARCH_FAILURE_MESSAGE,
    ReplyGenerationService,
)
from eva.images import GeneratedImage, GeneratedImageAsset, ImageClientError, ImageResultBundle
from eva.search import SearchClientError, SearchResultBundle


class StubResponseService:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


class StubSearchService:
    def __init__(
        self,
        *,
        result: SearchResultBundle | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error

    async def search_if_needed(self, **kwargs: object) -> SearchResultBundle | None:
        if self.error is not None:
            raise self.error
        return self.result


class StubSearchResponseService:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


class StubTOSCheckService:
    def __init__(self, *, is_violation: bool = False) -> None:
        self.is_violation = is_violation
        self.calls: list[str] = []

    async def check_tos_violation(self, text: str) -> bool:
        self.calls.append(text)
        return self.is_violation


class DummyChannel:
    pass


class DummyClient:
    pass


class StubImageService:
    def __init__(
        self,
        *,
        result: ImageResultBundle | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def generate_if_needed(self, **kwargs: object) -> ImageResultBundle | None:
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


def test_reply_generation_uses_normal_path_when_search_not_needed() -> None:
    response_service = StubResponseService("normal")
    tos_service = StubTOSCheckService()
    reply_service = ReplyGenerationService(
        response_service=response_service,
        image_service=StubImageService(result=None),
        search_service=StubSearchService(result=None),
        search_response_service=StubSearchResponseService("search"),
        tos_check_service=tos_service,
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="hello there",
            reply_context=None,
        )
    )

    assert reply.content == "normal"
    assert reply.attachments == []
    assert len(response_service.calls) == 1
    assert tos_service.calls == ["normal"]


def test_reply_generation_uses_search_path_when_results_exist() -> None:
    response_service = StubResponseService("normal")
    search_response_service = StubSearchResponseService("search")
    tos_service = StubTOSCheckService()
    reply_service = ReplyGenerationService(
        response_service=response_service,
        image_service=StubImageService(result=None),
        search_service=StubSearchService(result=SearchResultBundle(query="apple")),
        search_response_service=search_response_service,
        tos_check_service=tos_service,
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="apple stock price today",
            reply_context=None,
        )
    )

    assert reply.content == "search"
    assert reply.attachments == []
    assert len(search_response_service.calls) == 1
    assert response_service.calls == []
    assert tos_service.calls == ["search"]


def test_reply_generation_fails_closed_when_search_errors() -> None:
    reply_service = ReplyGenerationService(
        response_service=StubResponseService("normal"),
        image_service=StubImageService(result=None),
        search_service=StubSearchService(error=SearchClientError("boom")),
        search_response_service=StubSearchResponseService("search"),
        tos_check_service=StubTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="latest apple stock price",
            reply_context=None,
        )
    )

    assert reply.content == SEARCH_FAILURE_MESSAGE
    assert reply.attachments == []


def test_reply_generation_blocks_tos_violations() -> None:
    reply_service = ReplyGenerationService(
        response_service=StubResponseService("normal"),
        image_service=StubImageService(result=None),
        search_service=StubSearchService(result=None),
        search_response_service=StubSearchResponseService("search"),
        tos_check_service=StubTOSCheckService(is_violation=True),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="hello there",
            reply_context=None,
        )
    )

    assert "violates my safety or TOS guidelines" in reply.content
    assert reply.attachments == []


def test_reply_generation_uses_image_path_when_image_results_exist() -> None:
    response_service = StubResponseService("normal")
    search_response_service = StubSearchResponseService("search")
    tos_service = StubTOSCheckService()

    reply_service = ReplyGenerationService(
        response_service=response_service,
        image_service=StubImageService(
            result=ImageResultBundle(
                answer="Media generated: 'fox'",
                assets=[GeneratedImageAsset(filename="fox.png", data=b"png-bytes")],
            )
        ),
        search_service=StubSearchService(result=SearchResultBundle(query="apple")),
        search_response_service=search_response_service,
        tos_check_service=tos_service,
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="generate an image of a fox",
            reply_context=None,
        )
    )

    assert reply.content == "> fox"
    assert reply.attachments == [("fox.png", b"png-bytes")]
    assert response_service.calls == []
    assert search_response_service.calls == []
    assert tos_service.calls == ["> fox"]


def test_reply_generation_formats_image_url_fallback_as_blockquote() -> None:
    reply_service = ReplyGenerationService(
        response_service=StubResponseService("normal"),
        image_service=StubImageService(
            result=ImageResultBundle(
                answer="Media generated: 'A realistic chocolate chip cookie on a wooden table'",
                images=[GeneratedImage(url="https://example.com/cookie.png")],
            )
        ),
        search_service=StubSearchService(result=None),
        search_response_service=StubSearchResponseService("search"),
        tos_check_service=StubTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="generate an image of a cookie",
            reply_context=None,
        )
    )

    assert (
        reply.content
        == "> A realistic chocolate chip cookie on a wooden table\nhttps://example.com/cookie.png"
    )
    assert reply.attachments == []


def test_reply_generation_fails_closed_when_image_generation_errors() -> None:
    reply_service = ReplyGenerationService(
        response_service=StubResponseService("normal"),
        image_service=StubImageService(error=ImageClientError("boom")),
        search_service=StubSearchService(result=None),
        search_response_service=StubSearchResponseService("search"),
        tos_check_service=StubTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="make me an image",
            reply_context=None,
        )
    )

    assert reply.content == IMAGE_FAILURE_MESSAGE
    assert reply.attachments == []


def test_reply_generation_skips_image_path_for_reply_trigger() -> None:
    response_service = StubResponseService("normal")
    image_service = StubImageService(
        result=ImageResultBundle(
            answer="Media generated: 'fox'",
            assets=[GeneratedImageAsset(filename="fox.png", data=b"png-bytes")],
        )
    )
    reply_service = ReplyGenerationService(
        response_service=response_service,
        image_service=image_service,
        search_service=StubSearchService(result=None),
        search_response_service=StubSearchResponseService("search"),
        tos_check_service=StubTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="make it blue",
            reply_context="A red fox in the rain",
            allow_image_generation=False,
        )
    )

    assert reply.content == "normal"
    assert reply.attachments == []
    assert image_service.calls == []
    assert len(response_service.calls) == 1
