from eva.discord.formatting import build_response_text


def test_build_response_text_respects_discord_limit() -> None:
    original = "eva " + ("x" * 1200)
    reply = "y" * 2000

    out = build_response_text(original, reply)
    assert len(out) <= 2000


def test_build_response_text_contains_quote_prefix() -> None:
    out = build_response_text("eva test", "response")
    assert out.startswith("-# > eva test\n ")
