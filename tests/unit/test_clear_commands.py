from __future__ import annotations

import asyncio

from eva.discord.clear_commands import handle_clear_command


def test_clear_command_requires_admin_or_owner() -> None:
    response = asyncio.run(
        handle_clear_command(
            content="eva clear",
            user_id=999,
            is_owner=False,
            trigger_prefix="eva ",
        )
    )

    assert response.handled is True
    assert response.should_clear is False
    assert "don't have permission" in response.content


def test_clear_command_clears_for_admin() -> None:
    response = asyncio.run(
        handle_clear_command(
            content="eva clear",
            user_id=218675193592283137,
            is_owner=False,
            trigger_prefix="eva ",
        )
    )

    assert response.handled is True
    assert response.should_clear is True
    assert response.content == "✔ Cleared memory for this channel."


def test_clear_command_ignores_other_messages() -> None:
    response = asyncio.run(
        handle_clear_command(
            content="eva help",
            user_id=218675193592283137,
            is_owner=False,
            trigger_prefix="eva ",
        )
    )

    assert response.handled is False
