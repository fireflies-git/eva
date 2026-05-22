import asyncio
from pathlib import Path

from eva.discord.memory_commands import format_memories_for_prompt, handle_memory_command
from eva.state.user_memory import UserMemoryStore


def _run(coro):
    return asyncio.run(coro)


def test_remember_adds_a_note(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    response = _run(
        handle_memory_command(
            content="eva remember I prefer tea",
            user_id=1,
            trigger_prefix="eva ",
            memory_store=store,
        )
    )
    assert response.handled is True
    assert "Remembered" in response.content
    assert store.get(1) == ["I prefer tea"]


def test_remember_alone_lists_existing(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    store.add(1, "first")
    response = _run(
        handle_memory_command(
            content="eva remember",
            user_id=1,
            trigger_prefix="eva ",
            memory_store=store,
        )
    )
    assert response.handled is True
    assert "1. first" in response.content


def test_memories_lists(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    store.add(1, "one")
    store.add(1, "two")
    response = _run(
        handle_memory_command(
            content="eva memories",
            user_id=1,
            trigger_prefix="eva ",
            memory_store=store,
        )
    )
    assert response.handled is True
    assert "1. one" in response.content
    assert "2. two" in response.content


def test_forget_by_index(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    store.add(1, "first")
    store.add(1, "second")
    response = _run(
        handle_memory_command(
            content="eva forget 1",
            user_id=1,
            trigger_prefix="eva ",
            memory_store=store,
        )
    )
    assert response.handled is True
    assert "first" in response.content
    assert store.get(1) == ["second"]


def test_forget_all(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    store.add(1, "a")
    store.add(1, "b")
    response = _run(
        handle_memory_command(
            content="eva forget all",
            user_id=1,
            trigger_prefix="eva ",
            memory_store=store,
        )
    )
    assert response.handled is True
    assert "2" in response.content
    assert store.get(1) == []


def test_forget_out_of_range(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    response = _run(
        handle_memory_command(
            content="eva forget 99",
            user_id=1,
            trigger_prefix="eva ",
            memory_store=store,
        )
    )
    assert response.handled is True
    assert "No remembered fact" in response.content


def test_forget_malformed(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    response = _run(
        handle_memory_command(
            content="eva forget banana",
            user_id=1,
            trigger_prefix="eva ",
            memory_store=store,
        )
    )
    assert response.handled is True
    assert "Usage" in response.content


def test_unrelated_message_not_handled(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json")
    response = _run(
        handle_memory_command(
            content="eva hi there",
            user_id=1,
            trigger_prefix="eva ",
            memory_store=store,
        )
    )
    assert response.handled is False


def test_rejects_overlong_note(tmp_path: Path) -> None:
    store = UserMemoryStore(path=tmp_path / "memory.json", max_note_chars=5)
    response = _run(
        handle_memory_command(
            content="eva remember toolongtosave",
            user_id=1,
            trigger_prefix="eva ",
            memory_store=store,
        )
    )
    assert response.handled is True
    assert "too long" in response.content


def test_format_memories_for_prompt_returns_none_for_empty() -> None:
    assert format_memories_for_prompt([]) is None


def test_format_memories_for_prompt_renders_numbered_list() -> None:
    rendered = format_memories_for_prompt(["first", "second"])
    assert rendered is not None
    assert "Remembered facts" in rendered
    assert "1. first" in rendered
    assert "2. second" in rendered
