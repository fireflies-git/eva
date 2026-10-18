from eva.state.history import ChannelHistoryStore


def test_history_store_bounded_size() -> None:
    store = ChannelHistoryStore(max_messages_per_channel=2)
    store.append(1, "user", "one")
    store.append(1, "assistant", "two")
    store.append(1, "user", "three")

    history = store.get(1)
    assert len(history) == 2
    assert history[0]["content"] == "two"
    assert history[1]["content"] == "three"


def test_history_store_clear() -> None:
    store = ChannelHistoryStore(max_messages_per_channel=4)
    store.append_exchange(42, "hello", "hi")
    assert len(store.get(42)) == 2
    store.clear(42)
    assert store.get(42) == []


def test_history_store_evicts_least_recently_used_channels() -> None:
    store = ChannelHistoryStore(max_messages_per_channel=4, max_channels=2)
    store.append_exchange(1, "a", "b")
    store.append_exchange(2, "a", "b")
    store.get(1)  # touch 1 -> 2 becomes LRU
    store.append_exchange(3, "a", "b")  # adding 3 should evict 2

    assert store.get(1) != []
    assert store.get(2) == []
    assert store.get(3) != []


def test_history_store_get_does_not_create_entry() -> None:
    store = ChannelHistoryStore(max_channels=2)
    store.append_exchange(1, "a", "b")
    store.append_exchange(2, "a", "b")
    # Reading from a transient channel must not evict real channels.
    store.get(999)
    store.get(998)
    assert store.get(1) != []
    assert store.get(2) != []


def test_history_store_get_filters_expired_messages() -> None:
    now = [100.0]
    store = ChannelHistoryStore(max_messages_per_channel=4, clock=lambda: now[0])
    store.append(1, "user", "old")
    now[0] = 1000.0
    store.append(1, "assistant", "fresh")

    assert [m["content"] for m in store.get(1, max_age_seconds=300)] == ["fresh"]
    assert [m["content"] for m in store.get(1)] == ["old", "fresh"]


def test_history_store_get_returns_empty_when_everything_expired() -> None:
    now = [0.0]
    store = ChannelHistoryStore(clock=lambda: now[0])
    store.append_exchange(1, "a", "b")
    now[0] = 10_000.0

    assert store.get(1, max_age_seconds=60) == []
