from __future__ import annotations

import asyncio
from typing import Any, cast

import discord

from eva.account_updates import (
    AccountUpdateDraft,
    PendingAccountUpdateStore,
)
from eva.ai.account_updates import AccountUpdatePlanner
from eva.discord.account_updates import apply_account_update


class FakePlannerClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


def test_account_update_planner_parses_valid_update() -> None:
    client = FakePlannerClient(
        """
        {
          "is_account_update": true,
          "display_name": {"action": "set", "value": "Eva Prime"},
          "bio": {"action": "set", "value": "hello there"},
          "presence": {"action": "set", "value": "idle"},
          "custom_status": {"action": "set", "value": "scheming politely"}
        }
        """
    )
    planner = AccountUpdatePlanner(client=client, model_name="model")

    plan = asyncio.run(planner.plan_update("change your display name and status"))

    assert plan is not None
    assert plan.error is None
    assert plan.draft == AccountUpdateDraft(
        display_name="Eva Prime",
        bio="hello there",
        presence="idle",
        custom_status="scheming politely",
    )
    assert len(client.calls) == 1


def test_account_update_planner_asks_model_for_my_display_name_update() -> None:
    client = FakePlannerClient(
        """
        {
          "is_account_update": true,
          "display_name": {"action": "set", "value": "nerrou lover"},
          "bio": {"action": "none", "value": null},
          "presence": {"action": "none", "value": null},
          "custom_status": {"action": "none", "value": null}
        }
        """
    )
    planner = AccountUpdatePlanner(client=client, model_name="model")

    plan = asyncio.run(planner.plan_update("change my display name to nerrou lover"))

    assert plan is not None
    assert plan.error is None
    assert plan.draft == AccountUpdateDraft(display_name="nerrou lover")
    assert len(client.calls) == 1


def test_account_update_planner_skips_no_action_request() -> None:
    client = FakePlannerClient(
        """
        {
          "is_account_update": false,
          "display_name": {"action": "none", "value": null},
          "bio": {"action": "none", "value": null},
          "presence": {"action": "none", "value": null},
          "custom_status": {"action": "none", "value": null}
        }
        """
    )
    planner = AccountUpdatePlanner(client=client, model_name="model")

    plan = asyncio.run(planner.plan_update("what is your status right now"))

    assert plan is None
    assert client.calls == []


def test_account_update_planner_rejects_malformed_json() -> None:
    planner = AccountUpdatePlanner(
        client=FakePlannerClient("not json"),
        model_name="model",
    )

    plan = asyncio.run(planner.plan_update("change your status to idle"))

    assert plan is None


def test_account_update_planner_rejects_unsupported_status() -> None:
    planner = AccountUpdatePlanner(
        client=FakePlannerClient(
            """
            {
              "is_account_update": true,
              "display_name": {"action": "none", "value": null},
              "bio": {"action": "none", "value": null},
              "presence": {"action": "set", "value": "away"},
              "custom_status": {"action": "none", "value": null}
            }
            """
        ),
        model_name="model",
    )

    plan = asyncio.run(planner.plan_update("change your status to away"))

    assert plan is not None
    assert plan.error is not None
    assert "Presence must be one of" in plan.error


def test_account_update_planner_rejects_overlong_values() -> None:
    planner = AccountUpdatePlanner(
        client=FakePlannerClient(
            """
            {
              "is_account_update": true,
              "display_name": {"action": "set", "value": "abcdefghijklmnopqrstuvwxyzabcdefg"},
              "bio": {"action": "none", "value": null},
              "presence": {"action": "none", "value": null},
              "custom_status": {"action": "none", "value": null}
            }
            """
        ),
        model_name="model",
    )

    plan = asyncio.run(planner.plan_update("change your display name"))

    assert plan is not None
    assert plan.error is not None
    assert "Display name is too long" in plan.error


def test_pending_account_update_store_isolates_replaces_and_expires() -> None:
    now = 10.0

    def clock() -> float:
        return now

    store = PendingAccountUpdateStore(ttl_seconds=5.0, clock=clock)
    first = AccountUpdateDraft(display_name="first")
    second = AccountUpdateDraft(display_name="second")
    other = AccountUpdateDraft(display_name="other")

    store.set(user_id=1, channel_id=10, draft=first)
    store.set(user_id=1, channel_id=11, draft=other)
    store.set(user_id=1, channel_id=10, draft=second)

    first_pending = store.get(user_id=1, channel_id=10)
    other_pending = store.get(user_id=1, channel_id=11)
    assert first_pending is not None
    assert other_pending is not None
    assert first_pending.draft == second
    assert other_pending.draft == other

    now = 16.0

    assert store.get(user_id=1, channel_id=10) is None
    assert store.pop(user_id=1, channel_id=11) is None


class FakeUser:
    def __init__(self) -> None:
        self.edit_calls: list[dict[str, object]] = []

    async def edit(self, **kwargs: object) -> None:
        self.edit_calls.append(kwargs)


class FakeActivity:
    type = discord.ActivityType.playing


class FakeClient:
    def __init__(self) -> None:
        self.user = FakeUser()
        self.activities: list[Any] = [FakeActivity(), discord.CustomActivity(name="old")]
        self.presence_calls: list[dict[str, object]] = []

    async def change_presence(self, **kwargs: object) -> None:
        self.presence_calls.append(kwargs)


def test_apply_account_update_edits_profile_and_presence() -> None:
    client = FakeClient()
    draft = AccountUpdateDraft(
        display_name="Eva Prime",
        bio="new bio",
        presence="dnd",
        custom_status="working",
    )

    asyncio.run(apply_account_update(client=client, draft=draft))  # type: ignore[arg-type]

    assert client.user.edit_calls == [{"global_name": "Eva Prime", "bio": "new bio"}]
    assert client.presence_calls[0]["status"] == discord.Status.dnd
    activities = cast(list[object], client.presence_calls[0]["activities"])
    assert len(activities) == 2
    assert isinstance(activities[0], FakeActivity)
    assert isinstance(activities[1], discord.CustomActivity)
    assert str(activities[1]) == "working"


def test_apply_account_update_clears_custom_status_only() -> None:
    client = FakeClient()

    asyncio.run(
        apply_account_update(
            client=client,  # type: ignore[arg-type]
            draft=AccountUpdateDraft(clear_custom_status=True),
        )
    )

    assert client.user.edit_calls == []
    assert client.presence_calls == [{"activities": [client.activities[0]]}]
