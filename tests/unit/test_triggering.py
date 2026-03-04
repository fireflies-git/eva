from eva.discord.handlers import parse_trigger


def test_parse_trigger_with_prefix_message() -> None:
    result = parse_trigger(
        content="eva tell me a joke",
        trigger_prefix="eva ",
        is_reply_trigger=False,
    )
    assert result.should_process is True
    assert result.user_query == "tell me a joke"


def test_parse_trigger_reply_retrigger() -> None:
    result = parse_trigger(
        content="continue that",
        trigger_prefix="eva ",
        is_reply_trigger=True,
    )
    assert result.should_process is True
    assert result.user_query == "continue that"


def test_parse_trigger_non_match() -> None:
    result = parse_trigger(
        content="random message",
        trigger_prefix="eva ",
        is_reply_trigger=False,
    )
    assert result.should_process is False


def test_parse_trigger_empty_query_after_prefix() -> None:
    result = parse_trigger(
        content="eva ",
        trigger_prefix="eva ",
        is_reply_trigger=False,
    )
    assert result.should_process is False
