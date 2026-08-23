from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import cast

import discord

from eva.captcha import NopeCHAError
from eva.discord.friend_requests import FriendRequestHandler
from eva.discord.social_commands import SocialClient, handle_social_command
from eva.state import PendingFriendRequestStore

_ADMIN_ID = 218675193592283137
_TRIGGER_PREFIX = "eva "


def _captcha_exception() -> discord.CaptchaRequired:
    exception = discord.CaptchaRequired.__new__(discord.CaptchaRequired)
    exception.service = "hcaptcha"
    exception._sitekey = "sk"
    exception.errors = []
    exception.session_id = None
    exception.rqdata = None
    exception.rqtoken = None
    exception.should_serve_invisible = False
    return exception


class FakeRelationship:
    def __init__(self, *, request_type: discord.RelationshipType) -> None:
        self.type = request_type
        self.accepted = False
        self.deleted = False

    async def accept(self) -> None:
        self.accepted = True

    async def delete(self) -> None:
        self.deleted = True


class FakeSocialClient:
    def __init__(self) -> None:
        self.accepted_invites: list[str] = []
        self.relationships: dict[int, FakeRelationship] = {}
        self.invite_error: Exception | None = None

    async def accept_invite(self, url: str) -> discord.Invite:
        if self.invite_error is not None:
            raise self.invite_error
        self.accepted_invites.append(url)
        return cast(discord.Invite, SimpleNamespace(code="abc"))

    def get_relationship(self, user_id: int) -> FakeRelationship | None:
        return self.relationships.get(user_id)


def _run(
    *,
    content: str,
    user_id: int,
    is_owner: bool = False,
    client: FakeSocialClient | None = None,
    friend_request_handler: FriendRequestHandler | None = None,
):
    return asyncio.run(
        handle_social_command(
            content=content,
            user_id=user_id,
            is_owner=is_owner,
            trigger_prefix=_TRIGGER_PREFIX,
            client=cast(SocialClient | None, client),
            friend_request_handler=friend_request_handler,
        )
    )


def test_join_requires_admin() -> None:
    client = FakeSocialClient()

    response = _run(content="eva join https://discord.gg/abc", user_id=999, client=client)

    assert response.handled is True
    assert "don't have permission" in response.content
    assert client.accepted_invites == []


def test_join_accepts_invite_for_admin() -> None:
    client = FakeSocialClient()

    response = _run(
        content="eva join https://discord.gg/abc",
        user_id=_ADMIN_ID,
        client=client,
    )

    assert response.handled is True
    assert "Invite accepted" in response.content
    assert client.accepted_invites == ["https://discord.gg/abc"]


def test_join_accepts_invite_for_owner() -> None:
    client = FakeSocialClient()

    response = _run(
        content="eva join https://discord.gg/abc",
        user_id=1,
        is_owner=True,
        client=client,
    )

    assert response.handled is True
    assert client.accepted_invites == ["https://discord.gg/abc"]


def test_join_returns_usage_for_missing_invite() -> None:
    response = _run(content="eva join", user_id=_ADMIN_ID, client=FakeSocialClient())

    assert response.handled is True
    assert "Usage" in response.content


def test_join_failure_reports_error() -> None:
    client = FakeSocialClient()
    client.invite_error = RuntimeError("boom")

    response = _run(
        content="eva join https://discord.gg/abc",
        user_id=_ADMIN_ID,
        client=client,
    )

    assert response.handled is True
    assert "Join failed: boom" in response.content


def test_join_captcha_without_solver_warns_clearly() -> None:
    client = FakeSocialClient()
    client.invite_error = _captcha_exception()

    response = _run(
        content="eva join https://discord.gg/abc",
        user_id=_ADMIN_ID,
        client=client,
    )

    assert response.handled is True
    assert "blocked by captcha" in response.content


def test_join_nopecha_failure_warns_clearly() -> None:
    client = FakeSocialClient()
    client.invite_error = NopeCHAError("NopeCHA has no credit for this request")

    response = _run(
        content="eva join https://discord.gg/abc",
        user_id=_ADMIN_ID,
        client=client,
    )

    assert response.handled is True
    assert "Captcha solver failed" in response.content


def test_unrelated_content_is_not_handled() -> None:
    response = _run(content="hello there", user_id=_ADMIN_ID, client=FakeSocialClient())

    assert response.handled is False


def test_friends_accept_resolves_incoming_request() -> None:
    client = FakeSocialClient()
    relationship = FakeRelationship(request_type=discord.RelationshipType.incoming_request)
    client.relationships[123456] = relationship

    response = _run(
        content="eva friends accept 123456",
        user_id=_ADMIN_ID,
        client=client,
    )

    assert response.handled is True
    assert "Accepted friend request" in response.content
    assert relationship.accepted is True
    assert relationship.deleted is False


def test_friends_deny_rejects_incoming_request() -> None:
    client = FakeSocialClient()
    relationship = FakeRelationship(request_type=discord.RelationshipType.incoming_request)
    client.relationships[123456] = relationship

    response = _run(
        content="eva friends deny <@123456>",
        user_id=_ADMIN_ID,
        client=client,
    )

    assert response.handled is True
    assert "Denied friend request" in response.content
    assert relationship.deleted is True
    assert relationship.accepted is False


def test_friends_command_requires_admin() -> None:
    client = FakeSocialClient()
    client.relationships[123456] = FakeRelationship(
        request_type=discord.RelationshipType.incoming_request
    )

    response = _run(
        content="eva friends accept 123456",
        user_id=999,
        client=client,
    )

    assert response.handled is True
    assert "don't have permission" in response.content


def test_friends_command_warns_when_no_incoming_request() -> None:
    client = FakeSocialClient()
    client.relationships[123456] = FakeRelationship(request_type=discord.RelationshipType.friend)

    response = _run(
        content="eva friends accept 123456",
        user_id=_ADMIN_ID,
        client=client,
    )

    assert response.handled is True
    assert "No incoming friend request" in response.content


def test_friends_command_requires_target() -> None:
    response = _run(
        content="eva friends accept",
        user_id=_ADMIN_ID,
        client=FakeSocialClient(),
    )

    assert response.handled is True
    assert "Mention a user" in response.content


def test_friends_command_rejects_unknown_action() -> None:
    response = _run(
        content="eva friends maybe 123456",
        user_id=_ADMIN_ID,
        client=FakeSocialClient(),
    )

    assert response.handled is True
    assert "Usage" in response.content


def test_friends_accept_failure_reports_error() -> None:
    client = FakeSocialClient()

    class ExplodingRelationship(FakeRelationship):
        async def accept(self) -> None:
            raise RuntimeError("boom")

    client.relationships[123456] = ExplodingRelationship(
        request_type=discord.RelationshipType.incoming_request
    )

    response = _run(
        content="eva friends accept 123456",
        user_id=_ADMIN_ID,
        client=client,
    )

    assert response.handled is True
    assert "Failed to accept friend request: boom" in response.content


def test_friends_accept_nopecha_failure_warns() -> None:
    client = FakeSocialClient()

    class ExplodingRelationship(FakeRelationship):
        async def accept(self) -> None:
            raise NopeCHAError("NopeCHA has no credit for this request")

    client.relationships[123456] = ExplodingRelationship(
        request_type=discord.RelationshipType.incoming_request
    )

    response = _run(
        content="eva friends accept 123456",
        user_id=_ADMIN_ID,
        client=client,
    )

    assert response.handled is True
    assert "Captcha solver failed" in response.content


def test_top_level_accept_requires_and_resolves_pending_mention() -> None:
    client = FakeSocialClient()
    relationship = FakeRelationship(request_type=discord.RelationshipType.incoming_request)
    client.relationships[123456] = relationship
    store = PendingFriendRequestStore()
    store.set(
        requester_id=123456,
        requester_label="requester",
        review_text="body",
        notified_admin_ids=frozenset({_ADMIN_ID}),
    )
    handler = FriendRequestHandler(pending_store=store, admin_ids=[_ADMIN_ID])

    response = _run(
        content="eva accept <@123456>",
        user_id=_ADMIN_ID,
        client=client,
        friend_request_handler=handler,
    )

    assert response.handled is True
    assert "Accepted friend request" in response.content
    assert relationship.accepted is True
    assert store.get(requester_id=123456) is None


def test_top_level_deny_requires_a_mention() -> None:
    response = _run(
        content="eva deny 123456",
        user_id=_ADMIN_ID,
        client=FakeSocialClient(),
        friend_request_handler=FriendRequestHandler(
            pending_store=PendingFriendRequestStore(),
            admin_ids=[_ADMIN_ID],
        ),
    )

    assert response.handled is True
    assert "Mention a user" in response.content
