from eva.discord.formatting import build_plain_response_chunks, build_response_chunks


def test_build_response_chunks_respect_discord_limit() -> None:
    original = "eva " + ("x" * 1200)
    reply = "y" * 2000

    chunks = build_response_chunks(original, reply)
    assert chunks
    assert all(len(chunk) <= 2000 for chunk in chunks)


def test_build_response_chunks_contains_quote_prefix() -> None:
    chunks = build_response_chunks("eva test", "response")
    assert chunks[0].startswith("-# > eva test\n ")


def test_build_response_chunks_create_continuations() -> None:
    chunks = build_response_chunks("eva summarize", "x" * 6000)
    assert len(chunks) > 1
    assert chunks[1].startswith("-# (cont.)\n ")


def test_build_plain_response_chunks_respect_discord_limit() -> None:
    chunks = build_plain_response_chunks("x" * 6000)
    assert chunks
    assert all(len(chunk) <= 2000 for chunk in chunks)
