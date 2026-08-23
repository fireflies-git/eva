from eva.ai.sanitize import sanitize_response, strip_context_echo

_DSML_TOOL_CALL = (
    "<｜｜DSML｜｜tool_calls>\n"
    "<｜｜DSML｜｜invoke name=\"run_terminal_command\">\n"
    "<｜｜DSML｜｜parameter name=\"cmd\" string=\"true\">ping -c 3 10.0.0.2"
    "</｜｜DSML｜｜parameter>\n"
    "</｜｜DSML｜｜invoke>\n"
    "</｜｜DSML｜｜tool_calls>"
)


def test_sanitize_response_normalizes_em_dashes_and_unicode_emoji() -> None:
    assert sanitize_response("quiet — but okay 🙂") == "quiet , but okay"


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


def test_sanitize_response_keeps_text_around_dsml_tool_call() -> None:
    content = f"I checked that.\n{_DSML_TOOL_CALL}\nThe result is inconclusive."

    assert sanitize_response(content) == "I checked that.\n\nThe result is inconclusive."


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
