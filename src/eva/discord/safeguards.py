from __future__ import annotations

import logging
from collections.abc import Iterable

import discord

logger = logging.getLogger(__name__)


class DiscordSafeguardNotifier:
    """Send minimal safeguard alerts to the configured administrators."""

    def __init__(self, *, admin_ids: Iterable[int]) -> None:
        self._admin_ids = tuple(sorted(set(admin_ids)))

    async def notify_safeguard_hit(
        self,
        *,
        client: discord.Client,
        requester_id: int | None,
        channel_id: int | None,
        reason: str,
    ) -> None:
        requester = str(requester_id) if requester_id is not None else "unknown"
        channel = str(channel_id) if channel_id is not None else "unknown"
        body = (
            "⚠️ Eva safeguard hit\n"
            f"Reason: {reason}\n"
            f"Requester ID: {requester}\n"
            f"Channel ID: {channel}"
        )

        for admin_id in self._admin_ids:
            try:
                user = client.get_user(admin_id)
                if user is None:
                    user = await client.fetch_user(admin_id)
                try:
                    await user.send(body, allowed_mentions=discord.AllowedMentions.none())
                except TypeError as exc:
                    if "allowed_mentions" not in str(exc):
                        raise
                    await user.send(body)
            except Exception:
                logger.exception("Failed to DM admin %s about a safeguard hit", admin_id)
            else:
                logger.info("DM'd admin %s about a safeguard hit", admin_id)
