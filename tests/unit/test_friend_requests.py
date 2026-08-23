from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import discord

import eva.discord.handlers as handlers
from eva.ai import AIClientError, ReplyGenerationService
from eva.ai.friend_request_review import FriendRequestReview, FriendRequestReviewService
from eva.config import Settings
from eva.discord.friend_requests import (
    FriendRequestDecision,
    FriendRequestHandler,
    FriendRequestReviewer,
    build_friend_request_dm,
    parse_friend_request_confirmation,
    serialize_profile,
)
from eva.state import (
    ChannelHistoryStore,
    PendingFriendRequestStore,
    RateLimiter,
    ReminderStore,
    TrackedMessageStore,
    UserMemoryStore,
    WhitelistStore,
)

_ADMIN_ID = 218675193592283137
_OTHER_ADMIN_ID = 213766338005434370
_OWNER_ID = 1
_REQUESTER_ID = 42


class FakeUser:
    def __init__(self, user_id: int, *, name: str = "requester", bot: bool = False) -> None:
        self.id = user_id
        self.name = name
        self.discriminator = "0"
        self.display_name = name
        self.bot = bot
        self.sent: list[str] = []

    async def send(self, body: str) -> None:
        self.sent.append(body)


class FailingUser(FakeUser):
    async def send(self, body: str) -> None:
        raise RuntimeError("dm blocked")


class FakeBadge:
    def __init__(self, description: str) -> None:
        self.id = description
        self.description = description

    def __str__(self) -> str:
        return self.description


class FakeProfile:
    def __init__(
        self,
        *,
        user_id: int,
        name: str = "requester",
        bio: str = "",
        badges: list[FakeBadge] | None = None,
        mutual_friends: list[FakeUser] | None = None,
        mutual_guilds: list[object] | None = None,
    ) -> None:
        self.id = user_id
        self.name = name
        self.discriminator = "0"
        self.display_name = name
        self.bot = False
        self.bio = bio
        self.badges = badges or []
        self.mutual_friends = mutual_friends
        self.mutual_friends_count = None
        self.mutual_guilds = mutual_guilds


class FakeRelationship:
    def __init__(
        self,
        user: FakeUser,
        *,
        type_: discord.RelationshipType,
    ) -> None:
        self.user = user
        self.type = type_
        self.accepted = False
        self.deleted = False

    async def accept(self) -> None:
        self.accepted = True

    async def delete(self) -> None:
        self.deleted = True


class FakeGroup:
    def __init__(self, recipients: tuple[FakeUser, ...]) -> None:
        self.recipients = recipients
        self.name: str | None = None
        self.sent: list[str] = []

    async def edit(self, *, name: str) -> None:
        self.name = name

    async def send(self, content: str) -> None:
        self.sent.append(content)


class FakeDiscordClient:
    def __init__(
        self,
        *,
        profiles: dict[int, FakeProfile] | None = None,
        relationships: dict[int, FakeRelationship] | None = None,
        admin_users: dict[int, FakeUser] | None = None,
        owner_id: int = _OWNER_ID,
    ) -> None:
        self.profiles = profiles or {}
        self.relationships = relationships or {}
        self.admin_users = admin_users or {}
        self.user = SimpleNamespace(id=owner_id)
        self.profile_error: Exception | None = None
        self.groups: list[FakeGroup] = []

    async def fetch_user_profile(self, user_id: int, **kwargs: object) -> FakeProfile:
        if self.profile_error is not None:
            raise self.profile_error
        return self.profiles[user_id]

    def get_user(self, user_id: int) -> FakeUser | None:
        return self.admin_users.get(user_id)

    async def fetch_user(self, user_id: int) -> FakeUser:
        return self.admin_users[user_id]

    def get_relationship(self, user_id: int) -> FakeRelationship | None:
        return self.relationships.get(user_id)

    async def create_group(self, *recipients: FakeUser) -> FakeGroup:
        group = FakeGroup(recipients)
        self.groups.append(group)
        return group


class FakeReviewService:
    def __init__(self, review: FriendRequestReview | None) -> None:
        self.result = review
        self.calls: list[str] = []

    async def review(self, profile_text: str) -> FriendRequestReview | None:
        self.calls.append(profile_text)
        return self.result


def _relationship(user: FakeUser) -> FakeRelationship:
    return FakeRelationship(user, type_=discord.RelationshipType.incoming_request)


def _client_with_incoming(
    *,
    admin_ids: set[int] | None = None,
    profile: FakeProfile | None = None,
    requester: FakeUser | None = None,
) -> tuple[FakeDiscordClient, FakeRelationship]:
    requester = requester or FakeUser(_REQUESTER_ID)
    relationship = _relationship(requester)
    relationships = {_REQUESTER_ID: relationship}
    admin_users = {_ADMIN_ID: FakeUser(_ADMIN_ID, name="admin")}
    if admin_ids and _OTHER_ADMIN_ID in admin_ids:
        admin_users[_OTHER_ADMIN_ID] = FakeUser(_OTHER_ADMIN_ID, name="admin2")
    admin_users[_OWNER_ID] = FakeUser(_OWNER_ID, name="owner")
    client = FakeDiscordClient(
        profiles={_REQUESTER_ID: profile} if profile is not None else {},
        relationships=relationships,
        admin_users=admin_users,
    )
    return client, relationship


def test_incoming_request_dms_admins_and_stores_pending() -> None:
    profile = FakeProfile(
        user_id=_REQUESTER_ID,
        name="nerrou",
        bio="hello world",
        badges=[FakeBadge("Early Supporter")],
        mutual_friends=[FakeUser(7, name="mutual1")],
        mutual_guilds=[SimpleNamespace(guild=SimpleNamespace(name="Guild A"))],
    )
    client, _ = _client_with_incoming(profile=profile)
    store = PendingFriendRequestStore()
    review_service = FakeReviewService(
        FriendRequestReview(
            message=(
                "I got a friend request from nerrou. The profile has a consistent "
                "bio and a mutual friend, so I would trust it enough to accept."
            ),
            recommendation="accept",
        )
    )
    handler = FriendRequestHandler(
        pending_store=store,
        review_service=review_service,
        admin_ids=[_ADMIN_ID],
    )

    asyncio.run(
        handler.handle_incoming_request(
            client=cast(discord.Client, client),
            relationship=cast(discord.Relationship, client.relationships[_REQUESTER_ID]),
        )
    )

    admin = client.admin_users[_ADMIN_ID]
    owner = client.admin_users[_OWNER_ID]
    assert len(admin.sent) == 1
    assert len(owner.sent) == 1
    body = admin.sent[0]
    assert "I got a friend request from nerrou" in body
    assert "I would trust it enough to accept" in body
    assert "AI review" not in body
    assert "Reply `y` to accept" in body

    pending = store.get(requester_id=_REQUESTER_ID)
    assert pending is not None
    assert pending.notified_admin_ids == frozenset({_ADMIN_ID, _OWNER_ID})
    assert pending.review_text == body
    # The AI review received the serialized profile, not the raw user object.
    assert "Bio: hello world" in review_service.calls[0]


def test_incoming_request_without_review_service_uses_fallback_body() -> None:
    client, _ = _client_with_incoming()
    store = PendingFriendRequestStore()
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    asyncio.run(
        handler.handle_incoming_request(
            client=cast(discord.Client, client),
            relationship=cast(discord.Relationship, client.relationships[_REQUESTER_ID]),
        )
    )

    body = client.admin_users[_ADMIN_ID].sent[0]
    assert "AI review" not in body
    assert "I got a friend request" in body
    assert "I do not have enough information" in body
    assert "Reply `y` to accept" in body
    assert store.get(requester_id=_REQUESTER_ID) is not None


def test_bot_requests_are_ignored() -> None:
    requester = FakeUser(_REQUESTER_ID, bot=True)
    client, _ = _client_with_incoming(requester=requester)
    store = PendingFriendRequestStore()
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    asyncio.run(
        handler.handle_incoming_request(
            client=cast(discord.Client, client),
            relationship=cast(discord.Relationship, client.relationships[_REQUESTER_ID]),
        )
    )

    assert client.admin_users[_ADMIN_ID].sent == []
    assert store.get(requester_id=_REQUESTER_ID) is None


def test_non_incoming_relationship_is_ignored() -> None:
    requester = FakeUser(_REQUESTER_ID)
    client = FakeDiscordClient(
        admin_users={_ADMIN_ID: FakeUser(_ADMIN_ID, name="admin")},
    )
    relationship = FakeRelationship(requester, type_=discord.RelationshipType.friend)
    client.relationships[_REQUESTER_ID] = relationship
    store = PendingFriendRequestStore()
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    asyncio.run(
        handler.handle_incoming_request(
            client=cast(discord.Client, client),
            relationship=cast(discord.Relationship, relationship),
        )
    )

    assert client.admin_users[_ADMIN_ID].sent == []
    assert store.get(requester_id=_REQUESTER_ID) is None


def test_all_dm_failures_leave_request_unpendend() -> None:
    client, _ = _client_with_incoming()
    client.admin_users[_ADMIN_ID] = FailingUser(_ADMIN_ID, name="admin")
    client.admin_users[_OWNER_ID] = FailingUser(_OWNER_ID, name="owner")
    store = PendingFriendRequestStore()
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    asyncio.run(
        handler.handle_incoming_request(
            client=cast(discord.Client, client),
            relationship=cast(discord.Relationship, client.relationships[_REQUESTER_ID]),
        )
    )

    assert store.get(requester_id=_REQUESTER_ID) is None


def test_profile_fetch_failure_falls_back_to_basic_info() -> None:
    client, _ = _client_with_incoming()
    client.profile_error = RuntimeError("profile boom")
    store = PendingFriendRequestStore()
    review_service = FakeReviewService(None)
    handler = FriendRequestHandler(
        pending_store=store,
        review_service=review_service,
        admin_ids=[_ADMIN_ID],
    )

    asyncio.run(
        handler.handle_incoming_request(
            client=cast(discord.Client, client),
            relationship=cast(discord.Relationship, client.relationships[_REQUESTER_ID]),
        )
    )

    body = client.admin_users[_ADMIN_ID].sent[0]
    assert "Name: requester" in body
    assert store.get(requester_id=_REQUESTER_ID) is not None


def test_review_service_failure_falls_back_to_unreviewed_body() -> None:
    client, _ = _client_with_incoming()
    store = PendingFriendRequestStore()

    class ExplodingReviewService:
        async def review(self, profile_text: str) -> FriendRequestReview | None:
            raise RuntimeError("review boom")

    handler = FriendRequestHandler(
        pending_store=store,
        review_service=cast(FriendRequestReviewer, ExplodingReviewService()),
        admin_ids=[_ADMIN_ID],
    )

    asyncio.run(
        handler.handle_incoming_request(
            client=cast(discord.Client, client),
            relationship=cast(discord.Relationship, client.relationships[_REQUESTER_ID]),
        )
    )

    body = client.admin_users[_ADMIN_ID].sent[0]
    assert "AI review" not in body
    assert store.get(requester_id=_REQUESTER_ID) is not None


def test_confirmation_yes_accepts_request() -> None:
    client, relationship = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    result = asyncio.run(
        handler.handle_confirmation(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            content="y",
        )
    )

    assert result is not None
    assert "Accepted friend request" in result
    assert relationship.accepted is True
    assert relationship.deleted is False
    assert store.get(requester_id=_REQUESTER_ID) is None


def test_confirmation_no_denies_request() -> None:
    client, relationship = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    result = asyncio.run(
        handler.handle_confirmation(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            content="no",
        )
    )

    assert result is not None
    assert "Denied friend request" in result
    assert relationship.deleted is True
    assert relationship.accepted is False


def test_targeted_review_accepts_and_creates_application_group() -> None:
    client, relationship = _client_with_incoming(
        requester=FakeUser(_REQUESTER_ID, name="applicant")
    )
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="applicant",
        review_text="review body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    result = asyncio.run(
        handler.handle_targeted_review(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            requester_id=_REQUESTER_ID,
        )
    )

    assert "Accepted friend request" in result
    assert relationship.accepted is True
    assert store.get(requester_id=_REQUESTER_ID) is None
    assert len(client.groups) == 1
    group = client.groups[0]
    assert {user.id for user in group.recipients} == {_ADMIN_ID, _REQUESTER_ID}
    assert group.name == "applicant's Application"
    assert len(group.sent) == 1
    assert "Application started" in group.sent[0]


def test_targeted_review_without_target_uses_latest_pending_request() -> None:
    client, relationship = _client_with_incoming(
        requester=FakeUser(_REQUESTER_ID, name="latest applicant")
    )
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="latest applicant",
        review_text="review body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    result = asyncio.run(
        handler.handle_targeted_review(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            requester_id=None,
        )
    )

    assert "Accepted friend request" in result
    assert relationship.accepted is True
    assert len(client.groups) == 1


def test_targeted_review_rejects_admin_not_notified() -> None:
    client, relationship = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_OTHER_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    result = asyncio.run(
        handler.handle_targeted_review(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            requester_id=_REQUESTER_ID,
        )
    )

    assert "No pending friend request" in result
    assert relationship.accepted is False
    assert store.get(requester_id=_REQUESTER_ID) is not None


def test_targeted_review_reports_partial_success_when_group_setup_fails() -> None:
    client, relationship = _client_with_incoming()

    async def fail_create_group(*recipients: FakeUser) -> FakeGroup:
        raise RuntimeError("group unavailable")

    client.create_group = fail_create_group  # type: ignore[method-assign]
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    result = asyncio.run(
        handler.handle_targeted_review(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            requester_id=_REQUESTER_ID,
        )
    )

    assert relationship.accepted is True
    assert "application group setup failed" in result
    assert store.get(requester_id=_REQUESTER_ID) is None


def test_first_admin_reply_wins() -> None:
    client, relationship = _client_with_incoming(admin_ids={_ADMIN_ID, _OTHER_ADMIN_ID})
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID, _OTHER_ADMIN_ID}),
    )
    handler = FriendRequestHandler(
        pending_store=store,
        admin_ids=[_ADMIN_ID, _OTHER_ADMIN_ID],
    )

    first = asyncio.run(
        handler.handle_confirmation(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            content="yes",
        )
    )
    assert first is not None
    second = asyncio.run(
        handler.handle_confirmation(
            client=cast(discord.Client, client),
            admin_user_id=_OTHER_ADMIN_ID,
            content="deny",
        )
    )

    assert "Accepted" in first
    assert relationship.accepted is True
    # The second admin's late reply finds no pending request anymore.
    assert second is None
    assert relationship.deleted is False


def test_malformed_reply_is_ignored_and_pending_stays() -> None:
    client, _ = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    result = asyncio.run(
        handler.handle_confirmation(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            content="maybe?",
        )
    )

    assert result is None
    assert store.get(requester_id=_REQUESTER_ID) is not None


def test_reply_without_pending_falls_through() -> None:
    client, _ = _client_with_incoming()
    store = PendingFriendRequestStore()
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    result = asyncio.run(
        handler.handle_confirmation(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            content="y",
        )
    )

    assert result is None


def test_accept_failure_restores_pending_and_notifies() -> None:
    client, relationship = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    class ExplodingRelationship(FakeRelationship):
        async def accept(self) -> None:
            raise RuntimeError("boom")

    client.relationships[_REQUESTER_ID] = ExplodingRelationship(
        relationship.user,
        type_=discord.RelationshipType.incoming_request,
    )

    result = asyncio.run(
        handler.handle_confirmation(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            content="y",
        )
    )

    assert result is not None
    assert "Failed to accept friend request: boom" in result
    restored = store.get(requester_id=_REQUESTER_ID)
    assert restored is not None
    assert restored.notified_admin_ids == frozenset({_ADMIN_ID})


def test_already_resolved_request_warns_and_pops() -> None:
    client, _ = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])
    # The relationship vanished from the client cache (resolved elsewhere).
    client.relationships.pop(_REQUESTER_ID)

    result = asyncio.run(
        handler.handle_confirmation(
            client=cast(discord.Client, client),
            admin_user_id=_ADMIN_ID,
            content="y",
        )
    )

    assert result is not None
    assert "already resolved" in result
    assert store.get(requester_id=_REQUESTER_ID) is None


def test_pending_ttl_expiry_removes_entry() -> None:
    store = PendingFriendRequestStore(ttl_seconds=10.0)
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )

    assert store.get(requester_id=_REQUESTER_ID) is not None

    # Advance the clock past the TTL.
    entry = store._pending[_REQUESTER_ID]
    store._pending[_REQUESTER_ID] = replace(
        entry,
        created_monotonic=entry.created_monotonic - 11.0,
    )

    assert store.get(requester_id=_REQUESTER_ID) is None


def test_pending_requests_reload_from_disk(tmp_path) -> None:
    path = tmp_path / "pending_friend_requests.json"
    store = PendingFriendRequestStore(path=path)
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )

    reloaded = PendingFriendRequestStore(path=path)

    pending = reloaded.get(requester_id=_REQUESTER_ID)
    assert pending is not None
    assert pending.requester_label == "requester"
    assert pending.review_text == "body"
    assert pending.notified_admin_ids == frozenset({_ADMIN_ID})


def test_restart_notifies_admins_about_reloaded_pending_requests(tmp_path) -> None:
    path = tmp_path / "pending_friend_requests.json"
    initial_store = PendingFriendRequestStore(path=path)
    initial_store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="review body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    client, _ = _client_with_incoming()
    handler = FriendRequestHandler(
        pending_store=PendingFriendRequestStore(path=path),
        admin_ids=[_ADMIN_ID],
    )

    asyncio.run(handler.notify_pending_requests(client=cast(discord.Client, client)))

    assert len(client.admin_users[_ADMIN_ID].sent) == 1
    assert len(client.admin_users[_OWNER_ID].sent) == 1
    assert "Eva restarted" in client.admin_users[_ADMIN_ID].sent[0]
    assert "review body" in client.admin_users[_ADMIN_ID].sent[0]


def test_parse_friend_request_confirmation() -> None:
    assert parse_friend_request_confirmation("y") is FriendRequestDecision.ACCEPT
    assert parse_friend_request_confirmation("yes") is FriendRequestDecision.ACCEPT
    assert parse_friend_request_confirmation("accept") is FriendRequestDecision.ACCEPT
    assert parse_friend_request_confirmation("Y") is FriendRequestDecision.ACCEPT
    assert parse_friend_request_confirmation("n") is FriendRequestDecision.DENY
    assert parse_friend_request_confirmation("no") is FriendRequestDecision.DENY
    assert parse_friend_request_confirmation("deny") is FriendRequestDecision.DENY
    assert parse_friend_request_confirmation("reject") is FriendRequestDecision.DENY
    assert parse_friend_request_confirmation("maybe") is None
    assert parse_friend_request_confirmation("") is None


def test_serialize_profile_includes_signals() -> None:
    profile = FakeProfile(
        user_id=_REQUESTER_ID,
        name="nerrou",
        bio="hello",
        badges=[FakeBadge("Early Supporter")],
        mutual_friends=[FakeUser(7, name="mutual1"), FakeUser(8, name="mutual2")],
        mutual_guilds=[SimpleNamespace(guild=SimpleNamespace(name="Guild A"))],
    )

    text = serialize_profile(cast(discord.UserProfile, profile))

    assert "Name: nerrou" in text
    assert "Bio: hello" in text
    assert "Early Supporter" in text
    assert "Mutual friends (2): mutual1, mutual2" in text
    assert "Mutual guilds (1): Guild A" in text


def test_serialize_profile_includes_legacy_name() -> None:
    profile = FakeProfile(user_id=_REQUESTER_ID, name="nerrou")
    profile.discriminator = "1234"

    text = serialize_profile(cast(discord.UserProfile, profile))

    assert "Name: nerrou#1234" in text


def test_build_friend_request_dm_without_review() -> None:
    user = FakeUser(_REQUESTER_ID, name="nerrou")

    body = build_friend_request_dm(
        cast(discord.User, user),
        "Name: nerrou",
        None,
    )

    assert "I got a friend request" in body
    assert "Name: nerrou" in body
    assert "Reply `y` to accept" in body


# --- AI review service ---


class FakePlannerClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


class FailingClient:
    async def chat_completion(self, **kwargs: object) -> str:
        raise AIClientError("model down")


def test_review_service_parses_json_review() -> None:
    fake_client = FakePlannerClient(
        '{"message": "I got a friend request from nerrou. I would trust it.", '
        '"recommendation": "accept"}'
    )
    service = FriendRequestReviewService(
        client=fake_client,
        model_name="model",
        account_mode="standalone",
    )

    review = asyncio.run(service.review("Name: nerrou"))

    assert review == FriendRequestReview(
        message="I got a friend request from nerrou. I would trust it.",
        recommendation="accept",
    )
    assert len(fake_client.calls) == 1
    assert fake_client.calls[0]["model"] == "model"
    assert fake_client.calls[0]["temperature"] == 0.0
    messages = cast(list[dict[str, str]], fake_client.calls[0]["messages"])
    assert "You are Eva, a standalone Discord assistant account." in messages[0][
        "content"
    ]
    assert "review in Eva's voice" in messages[0]["content"]


def test_review_service_accepts_fenced_json() -> None:
    fake_client = FakePlannerClient(
        '```json\n{"message": "I got a friend request from nerrou. I am unsure.", '
        '"recommendation": "unsure"}\n```'
    )
    service = FriendRequestReviewService(client=fake_client, model_name="model")

    review = asyncio.run(service.review("Name: nerrou"))

    assert review is not None
    assert review.recommendation == "unsure"


def test_review_service_rejects_invalid_json() -> None:
    service = FriendRequestReviewService(
        client=FakePlannerClient("garbage output"),
        model_name="model",
    )

    assert asyncio.run(service.review("Name: nerrou")) is None


def test_review_service_rejects_bad_recommendation() -> None:
    service = FriendRequestReviewService(
        client=FakePlannerClient('{"message": "x", "recommendation": "maybe"}'),
        model_name="model",
    )

    assert asyncio.run(service.review("Name: nerrou")) is None


def test_review_service_rejects_missing_message() -> None:
    service = FriendRequestReviewService(
        client=FakePlannerClient('{"message": "", "recommendation": "accept"}'),
        model_name="model",
    )

    assert asyncio.run(service.review("Name: nerrou")) is None


def test_review_service_fails_open_on_client_error() -> None:
    service = FriendRequestReviewService(client=FailingClient(), model_name="model")

    assert asyncio.run(service.review("Name: nerrou")) is None


# --- handler integration: early DM confirmation ---


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
    def __init__(self, *, author_id: int, channel: DummyChannel, content: str) -> None:
        self.author = SimpleNamespace(id=author_id, display_name="user")
        self.channel = channel
        self.content = content
        self.id = 123
        self.reference = None
        self.mentions = []
        self.raw_mentions = []


class FailingReplyGenerationService:
    async def generate_reply(self, **kwargs: object) -> object:
        raise AssertionError("normal AI generation should not run")


def _build_handler(
    tmp_path,
    *,
    friend_request_handler: FriendRequestHandler,
    account_mode: str = "assistant",
):
    settings = _settings(account_mode=account_mode)
    return handlers.SelfbotMessageHandler(
        settings=settings,
        reply_generation_service=cast(
            ReplyGenerationService,
            FailingReplyGenerationService(),
        ),
        history_store=ChannelHistoryStore(),
        tracked_messages=TrackedMessageStore(path=tmp_path / "tracked.json"),
        whitelist=WhitelistStore(tmp_path / "whitelist.json"),
        user_memory=UserMemoryStore(path=tmp_path / "memory.json"),
        reminder_store=ReminderStore(path=tmp_path / "reminders.json"),
        rate_limiter=RateLimiter(max_requests=1_000_000, window_seconds=1.0),
        summarization_service=None,
        terminal_service=None,
        download_service=None,
        friend_request_handler=friend_request_handler,
    )


def test_admin_dm_reply_resolves_pending_before_whitelist_gate(
    monkeypatch,
    tmp_path,
) -> None:
    client, relationship = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])
    message_handler = _build_handler(tmp_path, friend_request_handler=handler)
    delivered: list[str] = []

    async def fake_deliver_reply_response(**kwargs: object) -> object:
        delivered.append(str(kwargs["reply_content"]))
        return SimpleNamespace(primary_delivered=True)

    monkeypatch.setattr(handlers, "deliver_reply_response", fake_deliver_reply_response)

    message = DummyMessage(
        author_id=_ADMIN_ID,
        channel=DummyChannel(99, guild=None),
        content="y",
    )

    asyncio.run(
        message_handler.on_message(
            cast(discord.Client, client),
            cast(discord.Message, message),
        )
    )

    assert relationship.accepted is True
    assert len(delivered) == 1
    assert "Accepted friend request" in delivered[0]


def test_guild_channel_reply_does_not_resolve_pending(monkeypatch, tmp_path) -> None:
    client, relationship = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])
    message_handler = _build_handler(tmp_path, friend_request_handler=handler)
    delivered: list[str] = []

    async def fake_deliver_reply_response(**kwargs: object) -> object:
        delivered.append(str(kwargs["reply_content"]))
        return SimpleNamespace(primary_delivered=True)

    monkeypatch.setattr(handlers, "deliver_reply_response", fake_deliver_reply_response)

    message = DummyMessage(
        author_id=_ADMIN_ID,
        channel=DummyChannel(99),  # guild channel: guild is not None
        content="y",
    )

    asyncio.run(
        message_handler.on_message(
            cast(discord.Client, client),
            cast(discord.Message, message),
        )
    )

    assert relationship.accepted is False
    assert delivered == []
    assert store.get(requester_id=_REQUESTER_ID) is not None


def test_non_admin_dm_reply_is_gated_out(monkeypatch, tmp_path) -> None:
    client, relationship = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])
    message_handler = _build_handler(tmp_path, friend_request_handler=handler)
    delivered: list[str] = []

    async def fake_deliver_reply_response(**kwargs: object) -> object:
        delivered.append(str(kwargs["reply_content"]))
        return SimpleNamespace(primary_delivered=True)

    monkeypatch.setattr(handlers, "deliver_reply_response", fake_deliver_reply_response)

    message = DummyMessage(
        author_id=999,
        channel=DummyChannel(99, guild=None),
        content="y",
    )

    asyncio.run(
        message_handler.on_message(
            cast(discord.Client, client),
            cast(discord.Message, message),
        )
    )

    assert relationship.accepted is False
    assert delivered == []
    assert store.get(requester_id=_REQUESTER_ID) is not None


def test_pending_requester_is_ignored_in_standalone_mode(monkeypatch, tmp_path) -> None:
    client, relationship = _client_with_incoming()
    store = PendingFriendRequestStore()
    store.set(
        requester_id=_REQUESTER_ID,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])
    message_handler = _build_handler(
        tmp_path,
        friend_request_handler=handler,
        account_mode="standalone",
    )
    delivered: list[str] = []

    async def fake_deliver_reply_response(**kwargs: object) -> object:
        delivered.append(str(kwargs["reply_content"]))
        return SimpleNamespace(primary_delivered=True)

    monkeypatch.setattr(handlers, "deliver_reply_response", fake_deliver_reply_response)

    message = DummyMessage(
        author_id=_REQUESTER_ID,
        channel=DummyChannel(99),
        content="hello Eva",
    )

    asyncio.run(
        message_handler.on_message(
            cast(discord.Client, client),
            cast(discord.Message, message),
        )
    )

    assert relationship.accepted is False
    assert delivered == []
    assert store.get(requester_id=_REQUESTER_ID) is not None
