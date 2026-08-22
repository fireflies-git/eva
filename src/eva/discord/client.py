from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

import discord

from eva.discord.handlers import SelfbotMessageHandler

logger = logging.getLogger(__name__)
interaction_logger = logging.getLogger("eva.interaction")

CaptchaHandler = Callable[[discord.CaptchaRequired, discord.Client], Awaitable[str]]


def create_discord_client(
    handler: SelfbotMessageHandler,
    *,
    captcha_handler: CaptchaHandler | None = None,
) -> discord.Client:
    client = discord.Client(
        chunk_guilds_at_startup=False,
        guild_subscriptions=False,
        member_cache_flags=discord.MemberCacheFlags.none(),
        captcha_handler=captcha_handler,
    )

    @client.event
    async def on_ready() -> None:
        user = client.user
        if user is None:
            logger.info("Eva connected to Discord")
            return
        logger.info("Eva online as %s (ID: %s)", user, user.id)
        interaction_logger.info(
            "ACCOUNT | username=%s display=%s id=%s",
            getattr(user, "name", "unknown"),
            getattr(user, "display_name", "unknown"),
            user.id,
        )

    @client.event
    async def on_message(message: discord.Message) -> None:
        await handler.on_message(client, message)

    @client.event
    async def on_relationship_add(relationship: discord.Relationship) -> None:
        await handler.on_relationship_add(client, relationship)

    return client
