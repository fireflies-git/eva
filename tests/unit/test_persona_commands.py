import asyncio
from pathlib import Path

import pytest

import eva.state.personas as personas_module
from eva.discord.command_outcome import CommandOutcome
from eva.discord.persona_commands import handle_persona_command
from eva.state.personas import PersonaStore


def _store(tmp_path: Path) -> PersonaStore:
    return PersonaStore(path=tmp_path / "personas.json")


def _run(
    store: PersonaStore,
    content: str,
    *,
    is_admin: bool = False,
    user_id: int = 1,
    channel_id: int = 100,
) -> CommandOutcome:
    return asyncio.run(
        handle_persona_command(
            content=content,
            user_id=user_id,
            channel_id=channel_id,
            trigger_prefix="eva ",
            is_admin=is_admin,
            persona_store=store,
        )
    )


@pytest.mark.parametrize("content", ["eva hello", "eva personality test", "persona list", ""])
def test_unrelated_content_is_not_handled(tmp_path: Path, content: str) -> None:
    assert _run(_store(tmp_path), content).handled is False


def test_admin_can_create_edit_delete(tmp_path: Path) -> None:
    store = _store(tmp_path)

    created = _run(store, "eva persona create pirate talk like a pirate", is_admin=True)
    assert created.handled and "Created" in created.content
    persona = store.get("pirate")
    assert persona is not None and persona.instructions == "talk like a pirate"

    edited = _run(store, "eva persona edit pirate be a polite pirate", is_admin=True)
    assert "Updated" in edited.content
    persona = store.get("pirate")
    assert persona is not None and persona.instructions == "be a polite pirate"

    deleted = _run(store, "eva persona delete pirate", is_admin=True)
    assert "Deleted" in deleted.content
    assert store.get("pirate") is None


@pytest.mark.parametrize(
    "content",
    [
        "eva persona create pirate arr",
        "eva persona edit pirate arr",
        "eva persona delete pirate",
        "eva persona channel pirate",
    ],
)
def test_non_admin_cannot_use_admin_verbs(tmp_path: Path, content: str) -> None:
    store = _store(tmp_path)
    store.create(name="pirate", instructions="arr", created_by=9)

    outcome = _run(store, content, is_admin=False)

    assert outcome.handled is True
    assert "Only the owner and admins" in outcome.content
    persona = store.get("pirate")
    assert persona is not None and persona.instructions == "arr"
    assert store.get_channel_active(100) is None


@pytest.mark.parametrize(
    "content",
    ["eva persona create", "eva persona create pirate", "eva persona edit pirate"],
)
def test_malformed_admin_commands_show_usage(tmp_path: Path, content: str) -> None:
    outcome = _run(_store(tmp_path), content, is_admin=True)
    assert outcome.handled is True
    assert "Usage" in outcome.content


def test_any_user_can_use_and_reset_their_persona(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(name="pirate", instructions="arr", created_by=9)

    used = _run(store, "eva persona use Pirate")
    assert "pirate" in used.content
    assert store.get_user_active(1) is not None

    assert "reset" in _run(store, "eva persona reset").content.lower()
    assert store.get_user_active(1) is None
    assert "no active persona" in _run(store, "eva persona reset").content


def test_use_unknown_persona_warns(tmp_path: Path) -> None:
    outcome = _run(_store(tmp_path), "eva persona use ghost")
    assert outcome.handled is True
    assert "No persona named `ghost`" in outcome.content


def test_use_without_name_shows_usage(tmp_path: Path) -> None:
    assert "Usage" in _run(_store(tmp_path), "eva persona use").content


def test_list_and_show(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert "No personas" in _run(store, "eva persona list").content

    store.create(name="pirate", instructions="arr matey", created_by=9)
    store.set_user_active(1, "pirate")
    listing = _run(store, "eva persona")
    assert "`pirate`" in listing.content
    assert "Yours: `pirate`" in listing.content
    assert "This channel: none" in listing.content

    assert "arr matey" in _run(store, "eva persona show pirate").content
    assert "No persona named" in _run(store, "eva persona show ghost").content


def test_admin_channel_set_and_reset(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(name="pirate", instructions="arr", created_by=9)

    set_outcome = _run(store, "eva persona channel pirate", is_admin=True)
    assert "This channel now uses" in set_outcome.content
    assert store.get_channel_active(100) is not None

    reset_outcome = _run(store, "eva persona channel reset", is_admin=True)
    assert "Channel persona reset" in reset_outcome.content
    assert store.get_channel_active(100) is None
    assert "no active persona" in _run(store, "eva persona channel reset", is_admin=True).content


def test_unknown_verb_shows_usage(tmp_path: Path) -> None:
    outcome = _run(_store(tmp_path), "eva persona dance")
    assert outcome.handled is True
    assert "Usage" in outcome.content


def test_persistence_failure_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(personas_module, "write_text_atomic", boom)

    outcome = _run(store, "eva persona create pirate arr", is_admin=True)

    assert outcome.handled is True
    assert "Failed to persist" in outcome.content
    assert store.get("pirate") is None
