"""Task 4: sliding window accounting, eviction, and concurrent access to one key."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from task4_model_router.rate_limiter import DEFAULT_LIMIT_TOKENS, SlidingWindowRateLimiter

KEY = "tenant-key-abc123"
OTHER_KEY = "tenant-key-zzz999"


@pytest.fixture
def limiter(tmp_path: Path) -> SlidingWindowRateLimiter:
    return SlidingWindowRateLimiter(tmp_path / "rate_limit.sqlite3", limit_tokens=50_000, window_seconds=60.0)


def test_the_brief_default_is_fifty_thousand_tokens_a_minute() -> None:
    assert DEFAULT_LIMIT_TOKENS == 50_000


def test_state_lives_in_a_file_on_disk(tmp_path: Path, limiter: SlidingWindowRateLimiter) -> None:
    limiter.try_consume(KEY, 10, now=1000.0)
    db_path = tmp_path / "rate_limit.sqlite3"
    assert db_path.exists()
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT key_digest, tokens FROM token_usage").fetchall()
    assert rows == [(limiter.key_digest(KEY), 10)]


def test_the_raw_api_key_is_never_written_to_disk(tmp_path: Path, limiter: SlidingWindowRateLimiter) -> None:
    """A leaked rate limit file must not hand back a tenant credential."""
    limiter.try_consume(KEY, 10, now=1000.0)
    limiter.close()
    for path in tmp_path.iterdir():
        assert KEY.encode() not in path.read_bytes(), f"raw api key found in {path.name}"


def test_a_pepper_changes_the_digest(tmp_path: Path) -> None:
    plain = SlidingWindowRateLimiter(tmp_path / "plain.sqlite3")
    peppered = SlidingWindowRateLimiter(tmp_path / "peppered.sqlite3", key_pepper=b"deployment secret")
    assert plain.key_digest(KEY) != peppered.key_digest(KEY)
    assert plain.key_digest(KEY) == plain.key_digest(KEY)
    assert plain.key_digest(KEY) != plain.key_digest(OTHER_KEY)


def test_a_request_that_fits_is_admitted(limiter: SlidingWindowRateLimiter) -> None:
    decision = limiter.try_consume(KEY, 50_000, now=1000.0)
    assert decision.allowed
    assert decision.tokens_in_window == 50_000
    assert decision.remaining_tokens == 0


def test_one_token_over_the_limit_is_rejected(limiter: SlidingWindowRateLimiter) -> None:
    assert limiter.try_consume(KEY, 50_000, now=1000.0).allowed
    decision = limiter.try_consume(KEY, 1, now=1000.0)
    assert not decision.allowed
    assert decision.tokens_in_window == 50_000


def test_a_rejected_request_is_not_charged(limiter: SlidingWindowRateLimiter) -> None:
    limiter.try_consume(KEY, 49_999, now=1000.0)
    limiter.try_consume(KEY, 5_000, now=1000.0)
    assert limiter.tokens_in_window(KEY, now=1000.0) == 49_999


def test_the_window_boundary_is_exact(limiter: SlidingWindowRateLimiter) -> None:
    """The window is the half open interval (now - 60, now].

    A charge at t is counted right up to t + 60 and has aged out at t + 60 exactly.
    """
    limiter.try_consume(KEY, 50_000, now=1000.0)
    assert not limiter.try_consume(KEY, 1, now=1000.0).allowed
    assert not limiter.try_consume(KEY, 1, now=1059.999).allowed
    assert limiter.try_consume(KEY, 50_000, now=1060.0).allowed


def test_the_window_slides_rather_than_resetting(limiter: SlidingWindowRateLimiter) -> None:
    """Two half budgets 30s apart free up 30s apart, not together on a fixed boundary."""
    assert limiter.try_consume(KEY, 25_000, now=1000.0).allowed
    assert limiter.try_consume(KEY, 25_000, now=1030.0).allowed
    assert not limiter.try_consume(KEY, 25_000, now=1050.0).allowed
    assert limiter.try_consume(KEY, 25_000, now=1060.1).allowed
    assert not limiter.try_consume(KEY, 25_000, now=1070.0).allowed
    assert limiter.try_consume(KEY, 25_000, now=1090.1).allowed


def test_expired_rows_are_deleted_not_just_ignored(limiter: SlidingWindowRateLimiter) -> None:
    for offset in range(10):
        limiter.try_consume(KEY, 100, now=1000.0 + offset)
    assert limiter.rows_for(KEY) == 10
    limiter.try_consume(KEY, 100, now=1064.5)
    assert limiter.rows_for(KEY) == 6, "rows older than the window should have been evicted"


def test_retry_after_points_at_when_room_appears(limiter: SlidingWindowRateLimiter) -> None:
    limiter.try_consume(KEY, 30_000, now=1000.0)
    limiter.try_consume(KEY, 20_000, now=1010.0)
    decision = limiter.try_consume(KEY, 25_000, now=1020.0)
    assert not decision.allowed
    # The oldest 30,000 tokens age out at 1060, which is the first moment 25,000 fits.
    assert decision.retry_after_seconds == pytest.approx(40.0)


def test_a_request_larger_than_the_whole_budget_is_never_admitted(limiter: SlidingWindowRateLimiter) -> None:
    decision = limiter.try_consume(KEY, 60_000, now=1000.0)
    assert not decision.allowed
    assert decision.retry_after_seconds == 60.0


def test_keys_have_separate_budgets(limiter: SlidingWindowRateLimiter) -> None:
    assert limiter.try_consume(KEY, 50_000, now=1000.0).allowed
    assert limiter.try_consume(OTHER_KEY, 50_000, now=1000.0).allowed
    assert not limiter.try_consume(KEY, 1, now=1000.0).allowed


def test_concurrent_requests_against_one_key_cannot_overspend(tmp_path: Path) -> None:
    """Twenty threads race for ten slots. Exactly ten get through, no more."""
    limiter = SlidingWindowRateLimiter(tmp_path / "race.sqlite3", limit_tokens=50_000, window_seconds=60.0)
    thread_count = 20
    charge = 5_000
    start = threading.Barrier(thread_count)
    results: list[bool] = []
    lock = threading.Lock()

    def worker() -> None:
        start.wait(timeout=10)
        decision = limiter.try_consume(KEY, charge)
        with lock:
            results.append(decision.allowed)
        limiter.close()

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(results) == thread_count
    assert sum(results) == 10, f"expected exactly 10 admissions, got {sum(results)}"
    assert limiter.tokens_in_window(KEY) == 50_000


def test_concurrent_requests_across_keys_do_not_block_each_other(tmp_path: Path) -> None:
    limiter = SlidingWindowRateLimiter(tmp_path / "keys.sqlite3", limit_tokens=1_000, window_seconds=60.0)
    keys = [f"tenant-{index}" for index in range(8)]
    outcomes: dict[str, bool] = {}
    lock = threading.Lock()

    def worker(key: str) -> None:
        decision = limiter.try_consume(key, 1_000)
        with lock:
            outcomes[key] = decision.allowed
        limiter.close()

    threads = [threading.Thread(target=worker, args=(key,)) for key in keys]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert all(outcomes.values())
    assert len(outcomes) == len(keys)


def test_state_survives_a_new_limiter_on_the_same_file(tmp_path: Path) -> None:
    path = tmp_path / "persist.sqlite3"
    first = SlidingWindowRateLimiter(path, limit_tokens=50_000, window_seconds=60.0)
    first.try_consume(KEY, 50_000, now=1000.0)
    first.close()

    second = SlidingWindowRateLimiter(path, limit_tokens=50_000, window_seconds=60.0)
    assert not second.try_consume(KEY, 1, now=1000.0).allowed


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"limit_tokens": 0}, "limit_tokens"), ({"window_seconds": 0}, "window_seconds")],
)
def test_rejects_a_nonsense_configuration(tmp_path: Path, kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SlidingWindowRateLimiter(tmp_path / "bad.sqlite3", **kwargs)  # type: ignore[arg-type]


def test_rejects_a_negative_charge(limiter: SlidingWindowRateLimiter) -> None:
    with pytest.raises(ValueError, match="tokens"):
        limiter.try_consume(KEY, -1)


def test_release_hands_the_budget_back(limiter: SlidingWindowRateLimiter) -> None:
    """A charge for a request that produced nothing can be given back."""
    decision = limiter.try_consume(KEY, 50_000, now=1000.0)
    assert decision.charge_id is not None
    assert limiter.release(decision.charge_id) is True
    assert limiter.tokens_in_window(KEY, now=1000.0) == 0
    assert limiter.rows_for(KEY) == 0
    assert limiter.try_consume(KEY, 50_000, now=1000.0).allowed


def test_releasing_an_unknown_charge_changes_nothing(limiter: SlidingWindowRateLimiter) -> None:
    limiter.try_consume(KEY, 100, now=1000.0)
    assert limiter.release(999_999) is False
    assert limiter.tokens_in_window(KEY, now=1000.0) == 100


def test_a_rejected_request_has_no_charge_to_release(limiter: SlidingWindowRateLimiter) -> None:
    limiter.try_consume(KEY, 50_000, now=1000.0)
    assert limiter.try_consume(KEY, 1, now=1000.0).charge_id is None
