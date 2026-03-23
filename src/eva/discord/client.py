from __future__ import annotations

import logging

import discord

from eva.discord.handlers import SelfbotMessageHandler

logger = logging.getLogger(__name__)
interaction_logger = logging.getLogger("eva.interaction")


def create_discord_client(handler: SelfbotMessageHandler) -> discord.Client:
    client = discord.Client(
        chunk_guilds_at_startup=False,
        guild_subscriptions=False,
        member_cache_flags=discord.MemberCacheFlags.none(),
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

    return client
