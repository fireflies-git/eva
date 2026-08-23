import asyncio
from typing import cast

import discord

from eva.ai import ResponseGenerationResult
from eva.ai.orchestrator import (
    IMAGE_FAILURE_MESSAGE,
    ReplyGenerationService,
)
from eva.constants import RESPONSE_WATERMARK
from eva.images import GeneratedImage, GeneratedImageAsset, ImageClientError, ImageResultBundle

_WM = "\n-# -eva"


class StubResponseService:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs: object) -> ResponseGenerationResult:
        self.calls.append(kwargs)
        return ResponseGenerationResult(self.response)


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


def test_reply_generation_uses_normal_text_path() -> None:
    response_service = StubResponseService("normal")
    tos_service = StubTOSCheckService()
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=response_service,
        image_service=StubImageService(result=None),
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
            requester_context=(
                "requester: user(id=1, username=neo, display_name=Neo, "
                "bio=unknown)"
            ),
        )
    )

    assert reply.content == f"normal{_WM}"
    assert reply.attachments == []
    assert len(response_service.calls) == 1
    assert response_service.calls[0]["requester_context"] is not None
    assert tos_service.calls == ["normal"]


def test_reply_generation_blocks_tos_violations() -> None:
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService("normal"),
        image_service=StubImageService(result=None),
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


def test_reply_generation_suppresses_dsml_tool_call_leak() -> None:
    leaked_tool_call = (
        "<｜｜DSML｜｜tool_calls>\n"
        "<｜｜DSML｜｜invoke name=\"run_terminal_command\">\n"
        "<｜｜DSML｜｜parameter name=\"cmd\" string=\"true\">ping -c 3 10.0.0.2"
        "</｜｜DSML｜｜parameter>\n"
        "</｜｜DSML｜｜invoke>\n"
        "</｜｜DSML｜｜tool_calls>"
    )
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService(leaked_tool_call),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="check the connection",
            reply_context=None,
        )
    )

    assert "DSML" not in reply.content
    assert "run_terminal_command" not in reply.content
    assert "couldn't complete that reply" in reply.content


def test_reply_generation_suppresses_identity_aware_transcript_leak() -> None:
    leaked_transcript = (
        "[11:16 message_id:1541043513542934598] @eva cutie patootie "
        "| gl:eva (pseudophilanthropic) [user_id:1008043568616718408] "
        "reply to @17povss (17povss) [user_id:1112785005144453373] "
        "[message_id:1541043501104373834]: hey."
    )
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService(leaked_transcript),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="hello",
            reply_context=None,
        )
    )

    assert "message_id" not in reply.content
    assert "pseudophilanthropic" not in reply.content
    assert "couldn't complete that reply" in reply.content


def test_reply_generation_uses_image_path_when_image_results_exist() -> None:
    response_service = StubResponseService("normal")
    tos_service = StubTOSCheckService()

    reply_service = ReplyGenerationService(
        response_service=response_service,
        image_service=StubImageService(
            result=ImageResultBundle(
                answer="Media generated: 'fox'",
                assets=[GeneratedImageAsset(filename="fox.png", data=b"png-bytes")],
            )
        ),
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

    assert reply.content == f"> fox{_WM}"
    assert reply.attachments == [("fox.png", b"png-bytes")]
    assert response_service.calls == []
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
        + _WM
    )
    assert reply.attachments == []


def test_reply_generation_fails_closed_when_image_generation_errors() -> None:
    reply_service = ReplyGenerationService(
        response_service=StubResponseService("normal"),
        image_service=StubImageService(error=ImageClientError("boom")),
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

    assert reply.content == f"{IMAGE_FAILURE_MESSAGE}{_WM}"
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

    assert reply.content == f"normal{_WM}"
    assert reply.attachments == []
    assert image_service.calls == []
    assert len(response_service.calls) == 1


def test_reply_generation_extracts_code_blocks_into_attachments() -> None:
    response = "Here is the code:\n\n```py\nprint('hello world')\n```\n\nRun it."
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService(response),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
    )

    reply = asyncio.run(
        reply_service.generate_reply(
            channel=cast(discord.abc.Messageable, DummyChannel()),
            client=cast(discord.Client, DummyClient()),
            context_messages=[],
            history_messages=[],
            user_message="write a python hello world",
            reply_context=None,
        )
    )

    assert reply.attachments == [("code.py", b"print('hello world')\n")]
    assert "`code.py`" in reply.content
    assert "```py" not in reply.content
    assert "```" not in reply.content
    assert "Run it." in reply.content


def test_reply_generation_deduplicates_model_emitted_watermark() -> None:
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService(f"here you go\n\n{RESPONSE_WATERMARK}"),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
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

    assert reply.content == f"here you go{_WM}"
    assert reply.content.count(RESPONSE_WATERMARK) == 1


def test_reply_generation_can_disable_watermark() -> None:
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService(f"here you go\n\n{RESPONSE_WATERMARK}"),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
    )
    reply_service.set_watermark_enabled(False)

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

    assert reply.content == "here you go"
    assert RESPONSE_WATERMARK not in reply.content


def test_reply_generation_can_reenable_watermark() -> None:
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService("here you go"),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
    )
    reply_service.set_watermark_enabled(False)
    reply_service.set_watermark_enabled(True)

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

    assert reply.content == f"here you go{_WM}"


def test_reply_generation_strips_context_echo_framing() -> None:
    echoed = (
        "[18:51] @eva (pseudophilanthropic) reply to @NeDIAD: still not gonna work "
        "(mentions: @NeDIAD (submissive.cunt))"
    )
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService(echoed),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
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

    assert reply.content == f"still not gonna work{_WM}"


def test_reply_generation_deduplicates_watermark_after_split_trigger() -> None:
    response = f"first part\n/// split\nsecond part\n{RESPONSE_WATERMARK}"
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService(response),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
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

    assert reply.content == f"first part\n/// split\nsecond part{_WM}"
    assert reply.content.count(RESPONSE_WATERMARK) == 1


def test_reply_generation_strips_trailing_split_trigger() -> None:
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService("the whole answer\n/// split"),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
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

    assert reply.content == f"the whole answer{_WM}"


def test_reply_generation_image_url_fallback_allows_embeds() -> None:
    reply_service = ReplyGenerationService(
        response_service=StubResponseService("normal"),
        image_service=StubImageService(
            result=ImageResultBundle(
                answer="Media generated: 'fox'",
                images=[GeneratedImage(url="https://example.com/fox.png")],
            )
        ),
        tos_check_service=StubTOSCheckService(),
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

    assert reply.allow_embeds is True


def test_reply_generation_normal_reply_suppresses_embeds() -> None:
    reply_service = ReplyGenerationService(
        account_mode="assistant",
        response_service=StubResponseService("normal"),
        image_service=StubImageService(result=None),
        tos_check_service=StubTOSCheckService(),
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

    assert reply.allow_embeds is False
