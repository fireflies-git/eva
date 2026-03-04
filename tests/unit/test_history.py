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
