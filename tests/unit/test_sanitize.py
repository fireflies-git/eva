from eva.ai.sanitize import (
    contains_all_caps_flood,
    contains_context_echo,
    contains_tool_call_markup,
    sanitize_response,
    strip_context_echo,
)

_DSML_TOOL_CALL = (
    "<｜｜DSML｜｜tool_calls>\n"
    "<｜｜DSML｜｜invoke name=\"run_terminal_command\">\n"
    "<｜｜DSML｜｜parameter name=\"cmd\" string=\"true\">ping -c 3 10.0.0.2"
    "</｜｜DSML｜｜parameter>\n"
    "</｜｜DSML｜｜invoke>\n"
    "</｜｜DSML｜｜tool_calls>"
)
_MALFORMED_DSML_TOOL_CALLS = (
    "\\</｜｜DSML｜｜ invoke>\n\\</｜｜DSML｜｜ calls>\n-# -eva",
    '<｜｜DSML｜｜ calls>\n<｜｜DSML｜｜ invoke name="inspect_attached_images">',
)


def test_sanitize_response_normalizes_em_dashes_and_unicode_emoji() -> None:
    assert sanitize_response("quiet — but okay 🙂") == "quiet , but okay"


def test_sanitize_response_preserves_emoji_only_reply() -> None:
    assert sanitize_response("🙂") == "🙂"


def test_sanitize_response_preserves_code_block_punctuation_and_symbols() -> None:
    content = "outside — text\n```python\nvalue = '— 🙂'\n```"

    assert sanitize_response(content) == "outside , text\n```python\nvalue = '— 🙂'\n```"


def test_sanitize_response_adds_question_mark_to_obvious_question() -> None:
    assert sanitize_response("How are you doing") == "How are you doing?"


def test_sanitize_response_does_not_change_code_question() -> None:
    content = "```text\nHow are you doing\n```"

    assert sanitize_response(content) == content


def test_sanitize_response_removes_dsml_tool_call_markup() -> None:
    assert sanitize_response(_DSML_TOOL_CALL) == ""


def test_sanitize_response_removes_malformed_dsml_tool_call_variants() -> None:
    for leaked_content in _MALFORMED_DSML_TOOL_CALLS:
        assert contains_tool_call_markup(leaked_content) is True
        assert sanitize_response(leaked_content) == ""


def test_sanitize_response_keeps_text_around_dsml_tool_call() -> None:
    content = f"I checked that.\n{_DSML_TOOL_CALL}\nThe result is inconclusive."

    assert sanitize_response(content) == "I checked that.\n\nThe result is inconclusive."


def test_contains_tool_call_markup_detects_protocol_without_blocking_text() -> None:
    content = f"I checked that.\n{_DSML_TOOL_CALL}"

    assert contains_tool_call_markup(content) is True
    assert sanitize_response(content) == "I checked that."


def test_strip_context_echo_removes_full_transcript_framing() -> None:
    echoed = (
        "[18:51] @eva (pseudophilanthropic) reply to @NeDIAD: still not gonna work. "
        "maybe pick something that doesn't instantly get flagged :3 "
        "(mentions: @NeDIAD (submissive.cunt))"
    )

    cleaned = strip_context_echo(echoed)

    expected = "still not gonna work. maybe pick something that doesn't instantly get flagged :3"
    assert cleaned == expected


def test_strip_context_echo_removes_speaker_label_without_timestamp() -> None:
    cleaned = strip_context_echo("@eva (pseudophilanthropic): hello there")

    assert cleaned == "hello there"


def test_strip_context_echo_removes_identity_aware_transcript_framing() -> None:
    echoed = (
        "eva: [20:29 message_id:1540820068954579020] "
        "@eva2freaky (pseudophilanthropic) [user_id:1008043568616718408]: "
        "i never said ugly, just that the confirmation process would be cursed"
    )

    cleaned = strip_context_echo(echoed)

    assert cleaned == ""


def test_strip_context_echo_removes_identity_aware_reply_metadata() -> None:
    echoed = (
        "[20:29 message_id:10] @Eva (eva) [user_id:1] reply to "
        "@Alice (alice) [user_id:2] [message_id:9]: understood"
    )

    assert strip_context_echo(echoed) == ""


def test_strip_context_echo_removes_current_discord_transcript_format() -> None:
    echoed = (
        "[UNTRUSTED_DISCORD_DATA 19:59 message_id:1553133974357378002] "
        "@eva (pseudophilanthropic) [user_id:1008043568616718408] "
        "reply to @leah (stupidorphan) [user_id:213766338005434370] "
        "[message_id:1553133967115296849]: leah what the fuck"
    )

    assert strip_context_echo(echoed) == ""
    assert strip_context_echo(f"I can answer that.\n{echoed}") == "I can answer that."


def test_strip_context_echo_drops_full_identity_aware_leak() -> None:
    echoed = (
        "[11:16 message_id:1541043513542934598] @eva cutie patootie "
        "| gl:eva (pseudophilanthropic) [user_id:1008043568616718408] "
        "reply to @17povss (17povss) [user_id:1112785005144453373] "
        "[message_id:1541043501104373834]: hey."
    )

    assert strip_context_echo(echoed) == ""


def test_strip_context_echo_keeps_plain_eva_speaker_label() -> None:
    content = "eva: i never said ugly"

    assert strip_context_echo(content) == content


def test_strip_context_echo_removes_each_transcript_line() -> None:
    echoed = "[18:51] @eva (tag): first line\n[18:52] @eva (tag) reply to @X: second line"

    cleaned = strip_context_echo(echoed)

    assert cleaned == "first line\nsecond line"


def test_strip_context_echo_removes_multi_mention_trailer() -> None:
    cleaned = strip_context_echo("nice try (mentions: @A (aaa); @B (bbb))")

    assert cleaned == "nice try"


def test_strip_context_echo_keeps_plain_mention_without_tag_group() -> None:
    content = "@NeDIAD: still not gonna work"

    assert strip_context_echo(content) == content


def test_strip_context_echo_keeps_bracketed_time_without_speaker() -> None:
    content = "[18:51] meeting moved"

    assert strip_context_echo(content) == content


def test_strip_context_echo_keeps_normal_content() -> None:
    content = "lol no. try again :3"

    assert strip_context_echo(content) == content


def test_strip_context_echo_handles_empty_input() -> None:
    assert strip_context_echo("") == ""


def test_contains_context_echo_detects_serialized_discord_metadata() -> None:
    echoed = (
        "answer first\n"
        "[UNTRUSTED_DISCORD_DATA 19:59 message_id:12] @alice (alice) "
        "[user_id:2]: copied line"
    )

    assert contains_context_echo(echoed) is True
    assert contains_context_echo("answer first") is False


def test_contains_all_caps_flood_allows_sparse_emphasis() -> None:
    assert contains_all_caps_flood("actually YOU are wrong") is False
    assert contains_all_caps_flood("you should NOT do that") is False


def test_contains_all_caps_flood_detects_repeated_prose_caps() -> None:
    content = "THIS RESPONSE HAS WAY TOO MANY CAPITALIZED WORDS AND KEEPS SHOUTING"

    assert contains_all_caps_flood(content) is True


def test_contains_all_caps_flood_ignores_code_urls_and_quotes() -> None:
    content = (
        'Use `THIS IS CODE` and https://example.test/THIS_PATH, then quote "THIS IS QUOTED".\n'
        "> THIS IS A BLOCKQUOTE"
    )

    assert contains_all_caps_flood(content) is False


def test_contains_all_caps_flood_ignores_short_acronyms() -> None:
    assert contains_all_caps_flood("HTTP JSON XML API SQL TCP UDP DNS") is False
