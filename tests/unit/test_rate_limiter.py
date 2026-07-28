import pytest

from eva.state.rate_limiter import _PRUNE_THRESHOLD_USERS, RateLimiter


def test_consumes_until_limit_then_blocks() -> None:
    limiter = RateLimiter(max_requests=2, window_seconds=60.0)
    assert limiter.check_and_consume(1) is True
    assert limiter.check_and_consume(1) is True
    assert limiter.check_and_consume(1) is False


def test_independent_per_user() -> None:
    limiter = RateLimiter(max_requests=1, window_seconds=60.0)
    assert limiter.check_and_consume(1) is True
    assert limiter.check_and_consume(2) is True
    assert limiter.check_and_consume(1) is False
    assert limiter.check_and_consume(2) is False


def test_window_slides_over_time() -> None:
    now = {"t": 0.0}

    def clock() -> float:
        return now["t"]

    limiter = RateLimiter(max_requests=2, window_seconds=10.0, clock=clock)
    assert limiter.check_and_consume(7) is True
    now["t"] = 1.0
    assert limiter.check_and_consume(7) is True
    now["t"] = 5.0
    assert limiter.check_and_consume(7) is False

    # Advance past the first event's window; it should expire.
    now["t"] = 10.5
    assert limiter.check_and_consume(7) is True


def test_exempt_user_never_blocked() -> None:
    limiter = RateLimiter(
        max_requests=1,
        window_seconds=60.0,
        exempt_user_ids={42},
    )
    for _ in range(50):
        assert limiter.check_and_consume(42) is True
    assert limiter.is_exempt(42) is True
    assert limiter.is_exempt(7) is False


def test_rejects_invalid_config() -> None:
    with pytest.raises(ValueError):
        RateLimiter(max_requests=0, window_seconds=10.0)
    with pytest.raises(ValueError):
        RateLimiter(max_requests=1, window_seconds=0.0)


def test_prunes_expired_user_entries_when_dict_grows() -> None:
    now = {"t": 0.0}

    def clock() -> float:
        return now["t"]

    limiter = RateLimiter(max_requests=1, window_seconds=10.0, clock=clock)
    for user_id in range(_PRUNE_THRESHOLD_USERS + 2):
        assert limiter.check_and_consume(user_id) is True

    # Every entry is expired; the next consume crosses the prune threshold.
    now["t"] = 100.0
    assert limiter.check_and_consume(999_999) is True
    assert len(limiter._events) <= 2


def test_keeps_active_user_entries_when_pruning() -> None:
    now = {"t": 0.0}

    def clock() -> float:
        return now["t"]

    limiter = RateLimiter(max_requests=1, window_seconds=100.0, clock=clock)
    for user_id in range(_PRUNE_THRESHOLD_USERS + 2):
        assert limiter.check_and_consume(user_id) is True

    # Entries are still inside the window, so pruning must not drop them.
    now["t"] = 1.0
    assert limiter.check_and_consume(999_999) is True
    assert len(limiter._events) > _PRUNE_THRESHOLD_USERS
    assert limiter.check_and_consume(0) is False
