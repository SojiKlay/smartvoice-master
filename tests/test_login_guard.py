"""Tests for the server-wide failed-login throttle."""

import pytest

from smartvoice import login_guard


@pytest.fixture(autouse=True)
def clean_guard():
    login_guard.clear_all()
    yield
    login_guard.clear_all()


def _fail(key, times, now, max_failures=5, lock_seconds=60):
    started = False
    for _ in range(times):
        started = login_guard.register_failure(key, max_failures, lock_seconds, now=now) or started
    return started


def test_account_locks_after_max_failures_and_unlocks_later():
    key = login_guard.account_key("Somchai")

    assert _fail(key, 4, now=1000.0) is False
    assert login_guard.lock_remaining(key, now=1000.0) == 0
    assert login_guard.failures_left(key, 5) == 1

    assert _fail(key, 1, now=1000.0) is True
    assert login_guard.lock_remaining(key, now=1000.0) == 60
    assert login_guard.lock_remaining(key, now=1059.5) == 1
    assert login_guard.lock_remaining(key, now=1060.0) == 0


def test_failures_during_a_lock_do_not_extend_it():
    key = login_guard.account_key("somchai")
    _fail(key, 5, now=1000.0)

    assert _fail(key, 10, now=1030.0) is False
    assert login_guard.lock_remaining(key, now=1060.0) == 0


def test_username_case_and_spaces_share_one_counter():
    """A new spelling of the same account must not get a fresh allowance."""
    assert login_guard.account_key(" Admin ") == login_guard.account_key("admin")


def test_counter_is_shared_across_sessions():
    """The old lockout lived in session_state; this one is process-wide."""
    key = login_guard.account_key("admin")
    _fail(key, 5, now=1000.0)

    # A "new session" is just another caller in the same process.
    assert login_guard.lock_remaining(login_guard.account_key("ADMIN"), now=1001.0) > 0


def test_reset_clears_an_account():
    key = login_guard.account_key("admin")
    _fail(key, 3, now=1000.0)
    login_guard.reset(key)

    assert login_guard.failures_left(key, 5) == 5


def test_unknown_client_is_never_throttled():
    assert login_guard.client_key(None) is None
    assert login_guard.client_key("  ") is None
    assert login_guard.register_failure(None, 1, 60) is False
    assert login_guard.lock_remaining(None) == 0
    login_guard.reset(None)


def test_client_and_account_keys_never_collide():
    assert login_guard.client_key("admin") != login_guard.account_key("admin")


def test_table_size_is_bounded(monkeypatch):
    monkeypatch.setattr(login_guard, "_MAX_TRACKED_KEYS", 50)
    for i in range(500):
        login_guard.register_failure(login_guard.account_key(f"user{i}"), 5, 60, now=1000.0)

    assert len(login_guard._entries) <= 50


def test_locked_entries_survive_pruning(monkeypatch):
    monkeypatch.setattr(login_guard, "_MAX_TRACKED_KEYS", 10)
    victim = login_guard.account_key("admin")
    _fail(victim, 5, now=1000.0)
    for i in range(100):
        login_guard.register_failure(login_guard.account_key(f"spray{i}"), 5, 60, now=1001.0)

    assert login_guard.lock_remaining(victim, now=1002.0) > 0
