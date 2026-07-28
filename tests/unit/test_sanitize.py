from eva.ai.sanitize import strip_context_echo


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
