from eva.discord.code_attachments import extract_code_blocks


def test_single_code_block_with_language() -> None:
    text = "Here is some code:\n\n```py\nprint('hello')\n```\n\nThat's it."

    result, attachments = extract_code_blocks(text)

    assert attachments == [("code.py", b"print('hello')\n")]
    assert "`code.py`" in result
    assert "```py" not in result
    assert "```" not in result


def test_multiple_code_blocks() -> None:
    text = "```py\nx = 1\n```\n\n```js\nconst y = 2;\n```"

    result, attachments = extract_code_blocks(text)

    assert len(attachments) == 2
    assert attachments[0] == ("code.py", b"x = 1\n")
    assert attachments[1] == ("code_2.js", b"const y = 2;\n")

    assert "`code.py`" in result
    assert "`code_2.js`" in result


def test_code_block_without_language_falls_back_to_txt() -> None:
    text = "```\necho hello\n```"

    result, attachments = extract_code_blocks(text)

    assert attachments == [("code.txt", b"echo hello\n")]
    assert "`code.txt`" in result


def test_empty_code_block_kept_inline() -> None:
    text = "before\n\n```py\n\n```\n\nafter"

    result, attachments = extract_code_blocks(text)

    assert attachments == []
    assert "```py" in result


def test_text_without_code_blocks_returns_unchanged() -> None:
    text = "Just a plain message.\n\nNo code here."

    result, attachments = extract_code_blocks(text)

    assert result == text
    assert attachments == []


def test_code_block_at_start_of_text() -> None:
    text = "```py\nprint('hi')\n```\n\nSome text after."

    result, attachments = extract_code_blocks(text)

    assert attachments == [("code.py", b"print('hi')\n")]
    assert "`code.py`" in result
    assert "Some text after." in result
    assert "```" not in result


def test_code_block_at_end_of_text() -> None:
    text = "Some text before.\n\n```js\nx = 1\n```"

    result, attachments = extract_code_blocks(text)

    assert attachments == [("code.js", b"x = 1\n")]
    assert "`code.js`" in result
    assert "Some text before." in result
    assert "```" not in result


def test_excessive_blank_lines_cleaned_up() -> None:
    text = "before\n\n\n\n```py\nx = 1\n```\n\n\n\nafter"

    result, attachments = extract_code_blocks(text)

    assert attachments == [("code.py", b"x = 1\n")]
    assert "\n\n\n" not in result
    assert "\n\n" in result


def test_empty_input() -> None:
    result, attachments = extract_code_blocks("")

    assert result == ""
    assert attachments == []


def test_multiple_languages_in_single_response() -> None:
    text = (
        "Python:\n\n```py\nprint('a')\n```\n\n"
        "Ruby:\n\n```rb\nputs 'b'\n```\n\n"
        "No tag:\n\n```\nplain\n```"
    )

    result, attachments = extract_code_blocks(text)

    assert len(attachments) == 3
    assert attachments[0] == ("code.py", b"print('a')\n")
    assert attachments[1] == ("code_2.rb", b"puts 'b'\n")
    assert attachments[2] == ("code_3.txt", b"plain\n")

    assert "`code.py`" in result
    assert "`code_2.rb`" in result
    assert "`code_3.txt`" in result
