import json
from pathlib import Path

import pytest

import eva.state.personas as personas_module
from eva.state.personas import PersonaError, PersonaPersistenceError, PersonaStore


def _store(tmp_path: Path, **kwargs: int) -> PersonaStore:
    return PersonaStore(path=tmp_path / "personas.json", **kwargs)


def test_create_normalizes_name_and_persists(tmp_path: Path) -> None:
    store = _store(tmp_path)
    persona = store.create(name="Pirate", instructions="  talk like a pirate  ", created_by=7)

    assert persona.name == "pirate"
    assert persona.instructions == "talk like a pirate"
    reloaded = _store(tmp_path)
    assert reloaded.get("PIRATE") == persona


@pytest.mark.parametrize("name", ["", "   ", "has space", "bad!", "-lead", "x" * 33])
def test_create_rejects_bad_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(PersonaError):
        _store(tmp_path).create(name=name, instructions="ok", created_by=1)


def test_create_rejects_empty_and_overlong_instructions(tmp_path: Path) -> None:
    store = _store(tmp_path, max_instruction_chars=10)
    with pytest.raises(PersonaError):
        store.create(name="a", instructions="   ", created_by=1)
    with pytest.raises(PersonaError):
        store.create(name="a", instructions="x" * 11, created_by=1)


def test_create_rejects_duplicates_and_capacity(tmp_path: Path) -> None:
    store = _store(tmp_path, max_personas=1)
    store.create(name="a", instructions="one", created_by=1)
    with pytest.raises(PersonaError):
        store.create(name="a", instructions="again", created_by=1)
    with pytest.raises(PersonaError):
        store.create(name="b", instructions="two", created_by=1)


def test_update_and_unknown_persona(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(name="a", instructions="one", created_by=1)
    assert store.update(name="a", instructions="two").instructions == "two"
    with pytest.raises(PersonaError):
        store.update(name="missing", instructions="x")


def test_delete_clears_activations(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(name="a", instructions="one", created_by=1)
    store.set_user_active(10, "a")
    store.set_channel_active(20, "a")

    store.delete("a")

    assert store.resolve(10, 20) is None
    assert _store(tmp_path).resolve(10, 20) is None


def test_resolve_prefers_user_over_channel(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(name="user-p", instructions="u", created_by=1)
    store.create(name="chan-p", instructions="c", created_by=1)
    store.set_channel_active(20, "chan-p")

    channel_persona = store.resolve(10, 20)
    assert channel_persona is not None and channel_persona.name == "chan-p"

    store.set_user_active(10, "user-p")
    user_persona = store.resolve(10, 20)
    assert user_persona is not None and user_persona.name == "user-p"
    other = store.resolve(11, 20)
    assert other is not None and other.name == "chan-p"
    assert store.resolve(None, None) is None


def test_clear_activation_reports_whether_anything_changed(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.create(name="a", instructions="one", created_by=1)
    assert store.clear_user_active(1) is False
    assert store.clear_channel_active(1) is False
    store.set_user_active(1, "a")
    assert store.clear_user_active(1) is True


def test_set_active_unknown_persona_raises(tmp_path: Path) -> None:
    with pytest.raises(PersonaError):
        _store(tmp_path).set_user_active(1, "nope")


def test_corrupt_or_wrong_shape_file_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "personas.json"
    path.write_text("{not json", encoding="utf-8")
    assert _store(tmp_path).list() == []
    path.write_text("[1, 2]", encoding="utf-8")
    assert _store(tmp_path).list() == []


def test_load_skips_invalid_entries_and_dangling_activations(tmp_path: Path) -> None:
    (tmp_path / "personas.json").write_text(
        json.dumps(
            {
                "personas": {
                    "good": {"instructions": "ok", "created_by": 1},
                    "Bad Name": {"instructions": "ok", "created_by": 1},
                    "empty": {"instructions": "  ", "created_by": 1},
                },
                "user_active": {"1": "good", "2": "ghost", "x": "good"},
                "channel_active": {"3": "good"},
            }
        ),
        encoding="utf-8",
    )
    store = _store(tmp_path)

    assert [p.name for p in store.list()] == ["good"]
    assert store.get_user_active(1) is not None
    assert store.get_user_active(2) is None
    assert store.get_channel_active(3) is not None


def test_failed_save_rolls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store(tmp_path)
    store.create(name="a", instructions="one", created_by=1)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(personas_module, "write_text_atomic", boom)

    with pytest.raises(PersonaPersistenceError):
        store.create(name="b", instructions="two", created_by=1)
    with pytest.raises(PersonaPersistenceError):
        store.set_user_active(1, "a")
    with pytest.raises(PersonaPersistenceError):
        store.delete("a")

    assert [p.name for p in store.list()] == ["a"]
    assert store.get_user_active(1) is None
