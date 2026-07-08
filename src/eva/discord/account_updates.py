from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import discord

from eva.account_updates import AccountUpdateDraft


class AccountUpdateApplyError(RuntimeError):
    pass


async def apply_account_update(*, client: discord.Client, draft: AccountUpdateDraft) -> None:
    user = client.user
    if user is None:
        raise AccountUpdateApplyError("Discord client user is unavailable.")

    edit_kwargs = _build_profile_edit_kwargs(draft)
    if edit_kwargs:
        edit = getattr(user, "edit", None)
        if edit is None:
            raise AccountUpdateApplyError("Discord client user cannot edit profile fields.")
        try:
            await edit(**edit_kwargs)
        except Exception as exc:
            raise AccountUpdateApplyError(f"Discord profile update failed: {exc}") from exc

    presence_kwargs = _build_presence_kwargs(client=client, draft=draft)
    if presence_kwargs:
        try:
            await client.change_presence(**presence_kwargs)
        except Exception as exc:
            raise AccountUpdateApplyError(f"Discord presence update failed: {exc}") from exc


def _build_profile_edit_kwargs(draft: AccountUpdateDraft) -> dict[str, str | None]:
    kwargs: dict[str, str | None] = {}
    if draft.display_name is not None:
        kwargs["global_name"] = draft.display_name
    elif draft.clear_display_name:
        kwargs["global_name"] = None

    if draft.bio is not None:
        kwargs["bio"] = draft.bio
    elif draft.clear_bio:
        kwargs["bio"] = None

    return kwargs


def _build_presence_kwargs(
    *,
    client: discord.Client,
    draft: AccountUpdateDraft,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}

    if draft.presence is not None:
        kwargs["status"] = _discord_status(draft.presence)

    if draft.custom_status is not None or draft.clear_custom_status:
        activities = _non_custom_activities(getattr(client, "activities", ()))
        if draft.custom_status is not None:
            activities.append(discord.CustomActivity(name=draft.custom_status))
        kwargs["activities"] = activities

    return kwargs


def _discord_status(presence: str) -> discord.Status:
    if presence == "online":
        return discord.Status.online
    if presence == "idle":
        return discord.Status.idle
    if presence == "dnd":
        return discord.Status.dnd
    if presence == "invisible":
        return discord.Status.invisible
    raise AccountUpdateApplyError(f"Unsupported presence: {presence}")


def _non_custom_activities(raw_activities: object) -> list[discord.BaseActivity]:
    if not isinstance(raw_activities, Sequence):
        return []

    activities: list[discord.BaseActivity] = []
    for activity in raw_activities:
        if getattr(activity, "type", None) == discord.ActivityType.custom:
            continue
        activities.append(activity)
    return activities
