from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import discord

import eva.discord.handlers as handlers
from eva.account_updates import AccountUpdateDraft, AccountUpdatePlan, PendingAccountUpdateStore
from eva.ai import ReplyGenerationService
from eva.ai.account_updates import AccountUpdatePlanner
from eva.ai.orchestrator import ReplyOutput
from eva.config import Settings
from eva.discord.delivery import DeliveryResult
from eva.state import (
    ChannelHistoryStore,
    RateLimiter,
    ReminderStore,
    TrackedMessageStore,
    UserMemoryStore,
    WhitelistStore,
)

_ADMIN_ID = 218675193592283137


def _settings(*, account_mode: str = "assistant") -> Settings:
    return cast(
        Settings,
        SimpleNamespace(
            account_mode=account_mode,
            trigger_prefix="eva ",
            response_context_messages=5,
            min_loading_seconds=0.0,
            followup_delay_min_seconds=0.0,
            followup_delay_max_seconds=0.0,
        ),
    )


def _rate_limiter() -> RateLimiter:
    return RateLimiter(max_requests=1_000_000, window_seconds=1.0)


class FakePlanner:
    def __init__(self, plan: AccountUpdatePlan | None) -> None:
        self.plan = plan
        self.calls: list[str] = []

    async def plan_update(self, user_message: str) -> AccountUpdatePlan | None:
        self.calls.append(user_message)
        return self.plan


class FakePlannerClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


def _account_update_response(*, display_name: str) -> str:
    return (
        "{"
        '"is_account_update": true,'
        f'"display_name": {{"action": "set", "value": "{display_name}"}},'
        '"bio": {"action": "none", "value": null},'
        '"presence": {"action": "none", "value": null},'
        '"custom_status": {"action": "none", "value": null}'
        "}"
    )


class FakeReplyGenerationService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def generate_reply(self, **kwargs: object) -> ReplyOutput:
        self.calls.append(kwargs)
        return ReplyOutput(content="normal reply", attachments=[])


class FailingReplyGenerationService:
    async def generate_reply(self, **kwargs: object) -> ReplyOutput:
        raise AssertionError("normal AI generation should not run")


class DummyTypingContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class DummyChannel:
    def __init__(self, channel_id: int, *, guild: object | None = object()) -> None:
        self.id = channel_id
        self.guild = guild

    def typing(self) -> DummyTypingContext:
        return DummyTypingContext()


class DummyMessage:
    def __init__(
        self,
        *,
        author_id: int,
        channel: DummyChannel,
        content: str,
    ) -> None:
        self.author = SimpleNamespace(id=author_id, display_name="user")
        self.channel = channel
        self.content = content
        self.id = 123
        self.reference = None
        self.mentions = []
        self.raw_mentions = []


class DummyClient:
    def __init__(self, user_id: int = 1) -> None:
        self.user = SimpleNamespace(id=user_id)


def _build_handler(
    tmp_path,
    *,
    account_mode: str = "assistant",
    planner: handlers.AccountUpdatePlanner | None = None,
    pending_store: PendingAccountUpdateStore | None = None,
    reply_generation_service: object | None = None,
    whitelist: WhitelistStore | None = None,
) -> handlers.SelfbotMessageHandler:
    return handlers.SelfbotMessageHandler(
        settings=_settings(account_mode=account_mode),
        reply_generation_service=cast(
            ReplyGenerationService,
            reply_generation_service or FailingReplyGenerationService(),
        ),
        history_store=ChannelHistoryStore(),
        tracked_messages=TrackedMessageStore(path=tmp_path / "tracked.json"),
        whitelist=whitelist or WhitelistStore(tmp_path / "whitelist.json"),
        user_memory=UserMemoryStore(path=tmp_path / "memory.json"),
        reminder_store=ReminderStore(path=tmp_path / "reminders.json"),
        rate_limiter=_rate_limiter(),
        summarization_service=None,
        terminal_service=None,
        download_service=None,
        account_update_planner=planner,
        pending_account_updates=pending_store or PendingAccountUpdateStore(),
    )


def test_authorized_account_update_request_creates_pending_confirmation(
    monkeypatch,
    tmp_path,
) -> None:
    draft = AccountUpdateDraft(display_name="Eva Prime")
    planner = FakePlanner(AccountUpdatePlan(draft=draft))
    pending_store = PendingAccountUpdateStore()
    handler = _build_handler(tmp_path, planner=planner, pending_store=pending_store)
    delivered: list[str] = []

    async def fake_deliver_owner_response(**kwargs: object) -> DeliveryResult:
        delivered.append(cast(str, kwargs["reply_content"]))
        return DeliveryResult(primary_delivered=True)

    monkeypatch.setattr(handlers, "deliver_owner_response", fake_deliver_owner_response)

    message = DummyMessage(
        author_id=1,
        channel=DummyChannel(99),
        content="eva change your display name to Eva Prime",
    )

    asyncio.run(
        handler.on_message(
            cast(discord.Client, DummyClient()),
            cast(discord.Message, message),
        )
    )

    assert planner.calls == ["change your display name to Eva Prime"]
    pending = pending_store.get(user_id=1, channel_id=99)
    assert pending is not None
    assert pending.draft == draft
    assert "Pending account update" in delivered[0]
    assert "Reply y to apply or n to cancel." in delivered[0]


def test_authorized_my_display_name_request_uses_confirmation_flow(
    monkeypatch,
    tmp_path,
) -> None:
    planner_client = FakePlannerClient(
        _account_update_response(display_name="nerrou lover"),
    )
    planner = AccountUpdatePlanner(
        client=planner_client,
        model_name="model",
    )
    pending_store = PendingAccountUpdateStore()
    handler = _build_handler(
        tmp_path,
        planner=planner,
        pending_store=pending_store,
    )
    delivered: list[str] = []

    async def fake_deliver_owner_response(**kwargs: object) -> DeliveryResult:
        delivered.append(cast(str, kwargs["reply_content"]))
        return DeliveryResult(primary_delivered=True)

    monkeypatch.setattr(handlers, "deliver_owner_response", fake_deliver_owner_response)

    message = DummyMessage(
        author_id=1,
        channel=DummyChannel(99),
        content="eva change my display name to nerrou lover",
    )

    asyncio.run(
        handler.on_message(
            cast(discord.Client, DummyClient()),
            cast(discord.Message, message),
        )
    )

    pending = pending_store.get(user_id=1, channel_id=99)
    assert pending is not None
    assert pending.draft == AccountUpdateDraft(display_name="nerrou lover")
    assert len(planner_client.calls) == 1
    assert "Pending account update" in delivered[0]
    assert "Display name -> 'nerrou lover'" in delivered[0]


def test_confirmation_y_applies_and_clears_pending(monkeypatch, tmp_path) -> None:
    draft = AccountUpdateDraft(presence="idle")
    pending_store = PendingAccountUpdateStore()
    pending_store.set(user_id=1, channel_id=99, draft=draft)
    handler = _build_handler(tmp_path, pending_store=pending_store)
    applied: list[AccountUpdateDraft] = []
    delivered: list[str] = []

    async def fake_apply_account_update(
        *,
        client: discord.Client,
        draft: AccountUpdateDraft,
    ) -> None:
        applied.append(draft)

    async def fake_deliver_owner_response(**kwargs: object) -> DeliveryResult:
        delivered.append(cast(str, kwargs["reply_content"]))
        return DeliveryResult(primary_delivered=True)

    monkeypatch.setattr(handlers, "apply_account_update", fake_apply_account_update)
    monkeypatch.setattr(handlers, "deliver_owner_response", fake_deliver_owner_response)

    message = DummyMessage(author_id=1, channel=DummyChannel(99), content="y")

    asyncio.run(
        handler.on_message(
            cast(discord.Client, DummyClient()),
            cast(discord.Message, message),
        )
    )

    assert applied == [draft]
    assert pending_store.get(user_id=1, channel_id=99) is None
    assert "Account update applied" in delivered[0]


def test_confirmation_n_cancels_and_clears_pending(monkeypatch, tmp_path) -> None:
    draft = AccountUpdateDraft(bio="new")
    pending_store = PendingAccountUpdateStore()
    pending_store.set(user_id=1, channel_id=99, draft=draft)
    handler = _build_handler(tmp_path, pending_store=pending_store)
    delivered: list[str] = []

    async def fake_deliver_owner_response(**kwargs: object) -> DeliveryResult:
        delivered.append(cast(str, kwargs["reply_content"]))
        return DeliveryResult(primary_delivered=True)

    monkeypatch.setattr(handlers, "deliver_owner_response", fake_deliver_owner_response)

    message = DummyMessage(author_id=1, channel=DummyChannel(99), content="n")

    asyncio.run(
        handler.on_message(
            cast(discord.Client, DummyClient()),
            cast(discord.Message, message),
        )
    )

    assert pending_store.get(user_id=1, channel_id=99) is None
    assert "cancelled" in delivered[0]


def test_unauthorized_assistant_request_is_denied(monkeypatch, tmp_path) -> None:
    whitelist = WhitelistStore(tmp_path / "whitelist.json")
    whitelist.add(2)
    planner = FakePlanner(AccountUpdatePlan(draft=AccountUpdateDraft(bio="new")))
    handler = _build_handler(tmp_path, planner=planner, whitelist=whitelist)
    delivered: list[str] = []

    async def fake_deliver_reply_response(**kwargs: object) -> DeliveryResult:
        delivered.append(cast(str, kwargs["reply_content"]))
        return DeliveryResult(primary_delivered=True)

    monkeypatch.setattr(handlers, "deliver_reply_response", fake_deliver_reply_response)

    message = DummyMessage(
        author_id=2,
        channel=DummyChannel(99),
        content="eva change your bio to new",
    )

    asyncio.run(
        handler.on_message(
            cast(discord.Client, DummyClient()),
            cast(discord.Message, message),
        )
    )

    assert "don't have permission" in delivered[0]


def test_standalone_admin_can_request_account_update(monkeypatch, tmp_path) -> None:
    draft = AccountUpdateDraft(custom_status="around")
    pending_store = PendingAccountUpdateStore()
    planner = FakePlanner(AccountUpdatePlan(draft=draft))
    handler = _build_handler(
        tmp_path,
        account_mode="standalone",
        planner=planner,
        pending_store=pending_store,
    )
    delivered: list[str] = []

    async def fake_deliver_reply_response(**kwargs: object) -> DeliveryResult:
        delivered.append(cast(str, kwargs["reply_content"]))
        return DeliveryResult(primary_delivered=True)

    monkeypatch.setattr(handlers, "deliver_reply_response", fake_deliver_reply_response)

    message = DummyMessage(
        author_id=_ADMIN_ID,
        channel=DummyChannel(99, guild=None),
        content="change your custom status to around",
    )

    asyncio.run(
        handler.on_message(
            cast(discord.Client, DummyClient()),
            cast(discord.Message, message),
        )
    )

    pending = pending_store.get(user_id=_ADMIN_ID, channel_id=99)
    assert pending is not None
    assert pending.draft == draft
    assert "Pending account update" in delivered[0]


def test_unrelated_y_without_pending_falls_through_normally(monkeypatch, tmp_path) -> None:
    reply_service = FakeReplyGenerationService()
    handler = _build_handler(
        tmp_path,
        account_mode="standalone",
        reply_generation_service=reply_service,
    )

    async def fake_context(
        channel: discord.abc.Messageable,
        *,
        limit: int,
        exclude_message_id: int | None = None,
    ) -> list[dict[str, str]]:
        return []

    async def fake_reply_context(message: discord.Message) -> str | None:
        return None

    async def fake_safe_reply(
        message: discord.Message,
        content: str,
        *,
        attachments: list[tuple[str, bytes]] | None = None,
    ) -> object:
        return SimpleNamespace(id=555)

    monkeypatch.setattr(handlers, "fetch_channel_context", fake_context)
    monkeypatch.setattr(handlers, "fetch_reply_context", fake_reply_context)
    monkeypatch.setattr(handlers, "safe_reply", fake_safe_reply)

    message = DummyMessage(author_id=2, channel=DummyChannel(99, guild=None), content="y")

    asyncio.run(
        handler.on_message(
            cast(discord.Client, DummyClient()),
            cast(discord.Message, message),
        )
    )

    assert len(reply_service.calls) == 1
