from __future__ import annotations

import asyncio
from typing import cast

import discord

from eva.discord.safeguards import DiscordSafeguardNotifier


class FakeUser:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, content: str) -> None:
        self.sent.append(content)


class FakeClient:
    def __init__(self, user: FakeUser) -> None:
        self.user = user

    def get_user(self, user_id: int) -> FakeUser | None:
        return self.user if user_id == 213766338005434370 else None

    async def fetch_user(self, user_id: int) -> FakeUser:
        return self.user


def test_safeguard_notifier_dms_configured_admin_without_reply_content() -> None:
    user = FakeUser()
    notifier = DiscordSafeguardNotifier(admin_ids={213766338005434370})

    asyncio.run(
        notifier.notify_safeguard_hit(
            client=cast(discord.Client, FakeClient(user)),
            requester_id=42,
            channel_id=99,
            reason="TOS moderation blocked generated content",
        )
    )

    assert user.sent == [
        "⚠️ Eva safeguard hit\n"
        "Reason: TOS moderation blocked generated content\n"
        "Requester ID: 42\n"
        "Channel ID: 99"
    ]


def test_safeguard_notifier_continues_when_admin_dm_fails() -> None:
    class FailingUser(FakeUser):
        async def send(self, content: str) -> None:
            raise RuntimeError("DM unavailable")

    notifier = DiscordSafeguardNotifier(admin_ids={213766338005434370})

    asyncio.run(
        notifier.notify_safeguard_hit(
            client=cast(discord.Client, FakeClient(FailingUser())),
            requester_id=None,
            channel_id=None,
            reason="protocol leak",
        )
    )


def test_safeguard_notifier_fetches_uncached_admin() -> None:
    user = FakeUser()

    class UncachedClient(FakeClient):
        def get_user(self, user_id: int) -> None:
            return None

    notifier = DiscordSafeguardNotifier(admin_ids={213766338005434370})

    asyncio.run(
        notifier.notify_safeguard_hit(
            client=cast(discord.Client, UncachedClient(user)),
            requester_id=42,
            channel_id=99,
            reason="protocol leak",
        )
    )

    assert len(user.sent) == 1
