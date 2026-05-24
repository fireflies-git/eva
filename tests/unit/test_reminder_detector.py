import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from eva.ai import AIClientError
from eva.reminders import ReminderDetector, looks_like_reminder

_NOW = datetime(2026, 5, 24, 12, 0, 0, tzinfo=UTC)


class FakeClient:
    def __init__(self, *, response: str = "{}", should_fail: bool = False) -> None:
        self.response = response
        self.should_fail = should_fail
        self.calls: list[dict[str, object]] = []

    async def chat_completion(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        if self.should_fail:
            raise AIClientError("boom")
        return self.response


@pytest.mark.parametrize(
    "text",
    [
        "remind me in 5m to take out the trash",
        "ping me in 2 hours",
        "alert me tomorrow about the meeting",
        "don't let me forget to call mom tonight",
        "in 30m bring trash",
        "ping me on tuesday",
        "wake me at 7am",
        "remind me next week to renew it",
    ],
)
def test_heuristic_gate_passes_for_reminder_like_messages(text: str) -> None:
    assert looks_like_reminder(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "hey",
        "lol",
        "what's 2+2",
        "do you like cats or dogs",
        "what time is it",
        "tell me a joke",
        "how does the tcp handshake work",
    ],
)
def test_heuristic_gate_skips_obvious_non_reminders(text: str) -> None:
    assert looks_like_reminder(text) is False


def test_detector_returns_intent_for_well_formed_response() -> None:
    fire_at = _NOW + timedelta(minutes=5)
    response = (
        '{"is_reminder": true, '
        f'"fire_at_iso": "{fire_at.isoformat()}", '
        '"text": "take out the trash"}'
    )
    detector = ReminderDetector(client=FakeClient(response=response), model_name="m")

    intent = asyncio.run(
        detector.detect(
            user_message="remind me in 5m to take out the trash",
            current_time=_NOW,
        )
    )

    assert intent is not None
    assert intent.fire_at == fire_at
    assert intent.text == "take out the trash"


def test_detector_skips_ai_call_when_heuristic_fails() -> None:
    client = FakeClient(response='{"is_reminder": true}')
    detector = ReminderDetector(client=client, model_name="m")

    intent = asyncio.run(
        detector.detect(user_message="hello there", current_time=_NOW)
    )

    assert intent is None
    assert client.calls == []


def test_detector_returns_none_on_invalid_json() -> None:
    detector = ReminderDetector(
        client=FakeClient(response="not json at all"), model_name="m"
    )
    intent = asyncio.run(
        detector.detect(user_message="remind me in 5m", current_time=_NOW)
    )
    assert intent is None


def test_detector_returns_none_on_is_reminder_false() -> None:
    detector = ReminderDetector(
        client=FakeClient(response='{"is_reminder": false}'), model_name="m"
    )
    intent = asyncio.run(
        detector.detect(user_message="remind me in 5m", current_time=_NOW)
    )
    assert intent is None


def test_detector_returns_none_for_past_fire_time() -> None:
    past = (_NOW - timedelta(minutes=5)).isoformat()
    response = (
        f'{{"is_reminder": true, "fire_at_iso": "{past}", "text": "thing"}}'
    )
    detector = ReminderDetector(client=FakeClient(response=response), model_name="m")
    intent = asyncio.run(
        detector.detect(user_message="remind me in 5m", current_time=_NOW)
    )
    assert intent is None


def test_detector_returns_none_for_empty_text() -> None:
    fire_at = (_NOW + timedelta(minutes=5)).isoformat()
    response = f'{{"is_reminder": true, "fire_at_iso": "{fire_at}", "text": "  "}}'
    detector = ReminderDetector(client=FakeClient(response=response), model_name="m")
    intent = asyncio.run(
        detector.detect(user_message="remind me in 5m", current_time=_NOW)
    )
    assert intent is None


def test_detector_handles_markdown_fenced_json() -> None:
    fire_at = _NOW + timedelta(hours=1)
    payload = (
        '{"is_reminder": true, '
        f'"fire_at_iso": "{fire_at.isoformat()}", '
        '"text": "call mom"}'
    )
    fenced = f"```json\n{payload}\n```"
    detector = ReminderDetector(client=FakeClient(response=fenced), model_name="m")
    intent = asyncio.run(
        detector.detect(user_message="remind me in 1h to call mom", current_time=_NOW)
    )
    assert intent is not None
    assert intent.text == "call mom"


def test_detector_handles_z_suffix_iso_timestamps() -> None:
    fire_at = _NOW + timedelta(minutes=30)
    z_form = fire_at.replace(tzinfo=None).isoformat() + "Z"
    response = f'{{"is_reminder": true, "fire_at_iso": "{z_form}", "text": "thing"}}'
    detector = ReminderDetector(client=FakeClient(response=response), model_name="m")
    intent = asyncio.run(
        detector.detect(user_message="remind me in 30m", current_time=_NOW)
    )
    assert intent is not None
    assert intent.fire_at == fire_at


def test_detector_falls_back_closed_on_ai_error() -> None:
    detector = ReminderDetector(
        client=FakeClient(should_fail=True), model_name="m"
    )
    intent = asyncio.run(
        detector.detect(user_message="remind me in 5m", current_time=_NOW)
    )
    assert intent is None


def test_detector_returns_none_on_empty_message() -> None:
    client = FakeClient(response='{"is_reminder": true}')
    detector = ReminderDetector(client=client, model_name="m")
    intent = asyncio.run(detector.detect(user_message="   ", current_time=_NOW))
    assert intent is None
    assert client.calls == []
