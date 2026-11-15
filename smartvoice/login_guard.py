"""Failed-login throttling shared by every browser session of this server process.

The old lockout lived in ``st.session_state``, so opening a new tab or session
started the count again — no protection once the app is reachable from the
internet. This module keeps the counters in process memory instead, keyed by
the account being tried and by the client address, so a new session does not
reset them.

Scope: one app process (the single-EC2 pilot). Several app instances behind a
load balancer would each keep their own counts; that setup needs a shared
store (database row or cache) instead. No Streamlit import, so it is unit-testable.
"""

import threading
import time

# An account locks after a few wrong passwords; a client address gets a larger
# allowance because a whole office can share one NAT address.
ACCOUNT_MAX_FAILURES = 5
ACCOUNT_LOCK_SECONDS = 60
CLIENT_MAX_FAILURES = 20
CLIENT_LOCK_SECONDS = 300

# Bound the memory an attacker can fill by trying random usernames.
_MAX_TRACKED_KEYS = 10_000

_lock = threading.Lock()
# key -> [failure_count, locked_until_epoch_seconds]
_entries: dict[str, list[float]] = {}


def account_key(username: str | None) -> str:
    """Throttle key for an account; usernames are case-insensitive."""
    return "user:" + (username or "").strip().lower()


def client_key(address: str | None) -> str | None:
    """Throttle key for a client address, or None when the address is unknown."""
    address = (address or "").strip()
    return "client:" + address if address else None


def _prune(now: float) -> None:
    """Drop entries that are no longer locked once the table grows too large."""
    if len(_entries) < _MAX_TRACKED_KEYS:
        return
    for key in [k for k, (_, until) in _entries.items() if until <= now]:
        del _entries[key]
    # Still full (an active flood): forget the oldest-inserted unlocked counters.
    if len(_entries) >= _MAX_TRACKED_KEYS:
        for key in list(_entries)[: len(_entries) - _MAX_TRACKED_KEYS + 1]:
            if _entries[key][1] <= now:
                del _entries[key]


def lock_remaining(key: str | None, now: float | None = None) -> int:
    """Seconds left on the lock for ``key`` (0 when not locked or key is None)."""
    if key is None:
        return 0
    now = time.time() if now is None else now
    with _lock:
        entry = _entries.get(key)
        if not entry:
            return 0
        remaining = entry[1] - now
    return max(0, int(remaining + 0.999))


def register_failure(key: str | None, max_failures: int, lock_seconds: int,
                     now: float | None = None) -> bool:
    """Count one failed attempt; return True when this failure starts a lock."""
    if key is None:
        return False
    now = time.time() if now is None else now
    with _lock:
        _prune(now)
        entry = _entries.setdefault(key, [0, 0.0])
        if entry[1] > now:
            return False
        entry[0] += 1
        if entry[0] >= max_failures:
            entry[0] = 0
            entry[1] = now + lock_seconds
            return True
        return False


def failures_left(key: str | None, max_failures: int) -> int:
    """Attempts left before ``key`` locks."""
    if key is None:
        return max_failures
    with _lock:
        entry = _entries.get(key)
        used = int(entry[0]) if entry else 0
    return max(0, max_failures - used)


def reset(key: str | None) -> None:
    """Forget the failures of ``key`` (after a successful login)."""
    if key is None:
        return
    with _lock:
        _entries.pop(key, None)


def clear_all() -> None:
    """Forget everything — for tests."""
    with _lock:
        _entries.clear()
