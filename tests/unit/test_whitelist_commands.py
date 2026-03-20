from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import discord

from eva.discord.commands import handle_whitelist_command
from eva.state import WhitelistStore


async def _capture_reply(
    message: discord.Message,
    is_owner: bool,
    content: str,
) -> None:
    captured = cast(list[tuple[bool, str]], message._captured)
    captured.append((is_owner, content))


def _make_message(*, author_id: int) -> discord.Message:
    message = SimpleNamespace(author=SimpleNamespace(id=author_id), _captured=[])
    return cast(discord.Message, message)


def _captured_messages(message: discord.Message) -> list[tuple[bool, str]]:
    return cast(list[tuple[bool, str]], message._captured)


def test_whitelist_list_command_is_still_available(tmp_path: Path) -> None:
    whitelist = WhitelistStore(tmp_path / "whitelist.json")
    whitelist.add(100)
    message = _make_message(author_id=100)

    handled = asyncio.run(
        handle_whitelist_command(
            message=message,
            content="eva whitelist list",
            is_owner=False,
            trigger_prefix="eva ",
            whitelist=whitelist,
            reply_or_edit=_capture_reply,
        )
    )

    assert handled is True
    assert _captured_messages(message) == [(False, "✔ Whitelisted: <@100>")]


def test_whitelist_add_is_blocked_for_non_admin(tmp_path: Path) -> None:
    whitelist = WhitelistStore(tmp_path / "whitelist.json")
    message = _make_message(author_id=999)

    handled = asyncio.run(
        handle_whitelist_command(
            message=message,
            content="eva whitelist add 123",
            is_owner=False,
            trigger_prefix="eva ",
            whitelist=whitelist,
            reply_or_edit=_capture_reply,
        )
    )

    assert handled is True
    assert whitelist.contains(123) is False
    assert _captured_messages(message) == [
        (False, "✖ You don't have permission to modify the whitelist.")
    ]


def test_whitelist_add_allows_hardcoded_admin_id(tmp_path: Path) -> None:
    whitelist = WhitelistStore(tmp_path / "whitelist.json")
    message = _make_message(author_id=218675193592283137)

    handled = asyncio.run(
        handle_whitelist_command(
            message=message,
            content="eva whitelist add 123",
            is_owner=False,
            trigger_prefix="eva ",
            whitelist=whitelist,
            reply_or_edit=_capture_reply,
        )
    )

    assert handled is True
    assert whitelist.contains(123) is True
    assert _captured_messages(message) == [(False, "✔ <@123> added to whitelist.")]
