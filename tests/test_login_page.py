"""The login page: server-wide lockout and never printing an operator's password."""

from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from smartvoice import auth, db, login_guard, ui_helpers


def _login_script():
    from smartvoice import ui_helpers

    ui_helpers.render_login_page()


@pytest.fixture
def login_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SMARTVOICE_USERS", "")
    monkeypatch.delenv(auth.BOOTSTRAP_PASSWORD_ENV, raising=False)
    db.init_db()
    user_id, error = auth.create_user("somchai", "correct-horse", "Agent", "Somchai")
    assert user_id and error is None
    login_guard.clear_all()
    yield
    login_guard.clear_all()


def _attempt(at: AppTest, username: str, password: str) -> AppTest:
    at.text_input(key="_login_username").input(username)
    at.text_input(key="_login_password").input(password)
    at.button[0].click()
    return at.run()


def _errors(at: AppTest) -> str:
    return " ".join(e.value for e in at.error)


def test_lock_survives_a_new_browser_session(login_env):
    first = AppTest.from_function(_login_script, default_timeout=30).run()
    for _ in range(login_guard.ACCOUNT_MAX_FAILURES):
        first = _attempt(first, "somchai", "wrong-password")
    assert "ถูกล็อก" in _errors(first)

    # A fresh AppTest is a separate Streamlit session — the old session_state
    # lockout reset here; the right password must still be refused.
    second = AppTest.from_function(_login_script, default_timeout=30).run()
    second = _attempt(second, "SOMCHAI", "correct-horse")

    assert "ถูกล็อก" in _errors(second)
    assert "current_user" not in second.session_state


def test_successful_login_clears_the_account_counter(login_env):
    at = AppTest.from_function(_login_script, default_timeout=30).run()
    _attempt(at, "somchai", "wrong-password")
    assert login_guard.failures_left(login_guard.account_key("somchai"), 5) == 4

    _attempt(at, "somchai", "correct-horse")

    assert login_guard.failures_left(login_guard.account_key("somchai"), 5) == 5


def test_published_default_is_shown_without_an_operator_password(monkeypatch, tmp_path):
    """Local behaviour is unchanged: the first-run hint still names admin1234."""
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SMARTVOICE_USERS", "")
    monkeypatch.delenv(auth.BOOTSTRAP_PASSWORD_ENV, raising=False)
    db.init_db()
    assert auth.ensure_default_admin() is True

    at = AppTest.from_function(_login_script, default_timeout=30).run()
    assert any(auth.DEFAULT_ADMIN_PASSWORD in i.value for i in at.info)


def test_operator_bootstrap_password_is_never_printed(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("SMARTVOICE_USERS", "")
    monkeypatch.setenv(auth.BOOTSTRAP_PASSWORD_ENV, "server-only-secret")
    db.init_db()
    assert auth.ensure_default_admin() is True

    at = AppTest.from_function(_login_script, default_timeout=30).run()
    shown = " ".join(i.value for i in at.info)

    assert "server-only-secret" not in shown
    assert auth.DEFAULT_ADMIN_PASSWORD not in shown
    assert auth.DEFAULT_ADMIN_USERNAME in shown


@pytest.mark.parametrize(
    ("peer", "forwarded", "expected"),
    [
        ("203.0.113.9", "", "203.0.113.9"),             # direct connection
        ("203.0.113.9", "198.51.100.1", "203.0.113.9"),  # header ignored when direct
        (None, "", None),                                # local use
        ("127.0.0.1", "198.51.100.7", "198.51.100.7"),   # behind the local proxy
        ("127.0.0.1", "10.0.0.1, 198.51.100.7", "198.51.100.7"),  # spoofed first hop ignored
        ("::1", "", None),
    ],
)
def test_client_address(monkeypatch, peer, forwarded, expected):
    headers = {"X-Forwarded-For": forwarded} if forwarded else {}
    fake = SimpleNamespace(context=SimpleNamespace(ip_address=peer, headers=headers))
    monkeypatch.setattr(ui_helpers, "st", fake)

    assert ui_helpers._client_address() == expected
