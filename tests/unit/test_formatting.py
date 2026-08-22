from eva.constants import DISCORD_MESSAGE_LIMIT
from eva.discord.formatting import (
    EMPTY_RESPONSE,
    build_loading_text,
    build_plain_response_chunks,
    build_response_chunks,
    split_on_text_triggers,
)


def test_build_response_chunks_respect_discord_limit() -> None:
    original = "eva " + ("x" * 1200)
    reply = "y" * 2000

    chunks = build_response_chunks(original, reply)
    assert chunks
    assert all(len(chunk) <= 2000 for chunk in chunks)


def test_build_response_chunks_contains_quote_prefix() -> None:
    chunks = build_response_chunks("eva test", "response")
    assert chunks[0].startswith("> eva test\n ")


def test_build_response_chunks_create_continuations() -> None:
    chunks = build_response_chunks("eva summarize", "x" * 6000)
    assert len(chunks) > 1
    assert chunks[1].startswith("-# (cont.)\n ")


def test_build_plain_response_chunks_split_on_paragraphs() -> None:
    reply = "first paragraph\n\nsecond paragraph\n\nthird paragraph"

    chunks = build_plain_response_chunks(reply, message_limit=25)

    assert chunks == ["first paragraph", "second paragraph", "third paragraph"]


def test_build_response_chunks_keep_code_block_together_when_it_fits() -> None:
    reply = "before\n\n```py\nprint('hi')\n```\n\nafter"

    chunks = build_response_chunks("eva test", reply, message_limit=80)

    assert len(chunks) == 3
    assert chunks[1].endswith("```py\nprint('hi')\n```")


def test_build_plain_response_chunks_respect_discord_limit() -> None:
    chunks = build_plain_response_chunks("x" * 6000)
    assert chunks
    assert all(len(chunk) <= 2000 for chunk in chunks)


def test_build_response_chunks_honor_split_trigger() -> None:
    chunks = build_response_chunks("eva hi", "part one\n/// split\npart two")

    assert len(chunks) == 2
    assert "part one" in chunks[0]
    assert "part two" in chunks[1]
    assert all("/// split" not in chunk for chunk in chunks)
    assert chunks[1].startswith("-# (cont.)")


def test_split_on_text_triggers_never_returns_empty() -> None:
    assert split_on_text_triggers("/// split") == [EMPTY_RESPONSE]
    assert split_on_text_triggers("/// split\n/// split") == [EMPTY_RESPONSE]


def test_build_plain_response_chunks_send_one_sentence_per_message() -> None:
    reply = "First sentence. Is this the second sentence? Yes, it is.\n-# -eva"

    chunks = build_plain_response_chunks(reply)

    assert chunks == [
        "First sentence",
        "Is this the second sentence?",
        "Yes, it is\n-# -eva",
    ]


def test_build_plain_response_chunks_keep_period_for_single_message() -> None:
    assert build_plain_response_chunks("One sentence.") == ["One sentence."]


def test_build_plain_response_chunks_hard_splits_single_sentence_at_limit() -> None:
    chunks = build_plain_response_chunks("x" * 2001 + ".")

    assert len(chunks) == 2
    assert all(len(chunk) <= DISCORD_MESSAGE_LIMIT for chunk in chunks)


def test_build_loading_text_stays_under_limit_for_long_prompts() -> None:
    loading = build_loading_text("x" * 5000)

    assert len(loading) <= DISCORD_MESSAGE_LIMIT
    assert "..." in loading
