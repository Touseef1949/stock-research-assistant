"""Unit tests for _ensure_user_row — verifies user-row creation/update logic.

These tests mock the Supabase client so they run offline and fast.
Previously _ensure_user_row was monkeypatched to a no-op in test_app.py,
so the actual insert/update logic was never exercised by any test.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, ANY


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_supabase_client(monkeypatch):
    """Return a mock Supabase admin client and wire it into payment.

    Only patches get_supabase_admin / get_supabase_client / _supabase_offline.
    The real get_user / _ensure_user_row code runs against the mock client,
    so we test the actual insert/update logic end-to-end.
    """
    sb = MagicMock()
    # All chainable methods return sb itself
    sb.table.return_value = sb
    sb.select.return_value = sb
    sb.eq.return_value = sb
    sb.limit.return_value = sb
    sb.insert.return_value = sb
    sb.update.return_value = sb

    # Separate execute results so select ≠ insert
    # Use side_effect to distinguish: first call = select, second call = insert
    select_result = MagicMock()
    select_result.data = []  # default: no existing user
    insert_result = MagicMock()
    insert_result.data = []  # default: empty insert

    # track execute calls to return the right result
    call_count = [0]

    def _execute():
        call_count[0] += 1
        if call_count[0] <= 2:  # first couple calls are from get_user (select chain)
            return select_result
        return insert_result

    sb.execute.side_effect = _execute

    # Also expose these so tests can configure them
    sb._select_result = select_result
    sb._insert_result = insert_result

    import payment
    monkeypatch.setattr(payment, "get_supabase_admin", lambda: sb)
    monkeypatch.setattr(payment, "get_supabase_client", lambda: sb)
    monkeypatch.setattr(payment, "_supabase_offline", lambda: False)

    return sb


@pytest.fixture()
def mock_offline(monkeypatch):
    """Simulate Supabase being unavailable."""
    import payment
    monkeypatch.setattr(payment, "get_supabase_admin", lambda: None)
    monkeypatch.setattr(payment, "_supabase_offline", lambda: True)


# ---------------------------------------------------------------------------
# New user tests
# ---------------------------------------------------------------------------

class TestEnsureUserRowNewUser:
    """When no public.users row exists yet."""

    def test_creates_row_for_new_user(self, mock_supabase_client):
        from payment import _ensure_user_row

        mock_supabase_client._select_result.data = []  # no existing user
        mock_supabase_client._insert_result.data = [
            {"email": "new@test.com", "plan": "free", "analyses_used": 0,
             "analyses_limit": 5, "created_at": ANY, "id": 42}
        ]

        result = _ensure_user_row("new@test.com")

        assert result is not None
        assert result["email"] == "new@test.com"
        assert result["plan"] == "free"
        # insert() was called
        mock_supabase_client.insert.assert_called_once()

    def test_payload_has_no_uuid_id(self, mock_supabase_client):
        """Insert payload must NOT contain 'id' (BIGSERIAL auto-increment)."""
        from payment import _ensure_user_row

        mock_supabase_client._select_result.data = []
        _ensure_user_row("user@test.com")

        call_args = mock_supabase_client.insert.call_args
        assert call_args is not None, "insert was never called"
        # insert(row) → first positional arg is the row dict
        row = call_args[0][0]
        assert "id" not in row, f"Insert payload must not set 'id': got {row}"

    def test_payload_has_no_nonexistent_columns(self, mock_supabase_client):
        """Insert payload must NOT contain confirmed_at or last_login_at."""
        from payment import _ensure_user_row

        mock_supabase_client._select_result.data = []
        _ensure_user_row("user@test.com")

        call_args = mock_supabase_client.insert.call_args
        row = call_args[0][0]
        for bad_col in ("confirmed_at", "last_login_at"):
            assert bad_col not in row, \
                f"Insert payload must not contain '{bad_col}': got {row}"

    def test_payload_has_required_columns(self, mock_supabase_client):
        """Insert payload must have email, plan, analyses_used, analyses_limit, created_at."""
        from payment import _ensure_user_row

        mock_supabase_client._select_result.data = []
        _ensure_user_row("user@test.com")

        call_args = mock_supabase_client.insert.call_args
        row = call_args[0][0]
        for col in ("email", "plan", "analyses_used", "analyses_limit", "created_at"):
            assert col in row, f"Missing required column '{col}' in: {row}"

    def test_new_user_defaults_to_free(self, mock_supabase_client):
        from payment import _ensure_user_row

        mock_supabase_client._select_result.data = []
        _ensure_user_row("regular@test.com")

        call_args = mock_supabase_client.insert.call_args
        row = call_args[0][0]
        assert row["plan"] == "free"
        assert row["analyses_limit"] == 5


# ---------------------------------------------------------------------------
# Returning user tests
# ---------------------------------------------------------------------------

class TestEnsureUserRowReturning:
    """When a public.users row already exists."""

    def test_does_not_duplicate_existing_user(self, mock_supabase_client):
        from payment import _ensure_user_row
        import payment as pm

        existing = {
            "id": 1, "email": "existing@test.com", "plan": "free",
            "analyses_used": 3, "analyses_limit": 5,
            "created_at": "2026-01-01",
        }
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(pm, "get_user", lambda email: existing)

        result = _ensure_user_row("existing@test.com")

        # Should not call insert
        mock_supabase_client.insert.assert_not_called()
        assert result is not None
        monkeypatch.undo()

    def test_returns_existing_user_data(self, mock_supabase_client):
        from payment import _ensure_user_row
        import payment as pm

        existing = {
            "id": 1, "email": "ret@test.com", "plan": "free",
            "analyses_used": 2, "analyses_limit": 5,
            "created_at": "2026-01-01",
        }
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(pm, "get_user", lambda email: existing)

        result = _ensure_user_row("ret@test.com")

        assert result is not None
        assert result["email"] == "ret@test.com"
        assert result["plan"] == "free"
        monkeypatch.undo()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEnsureUserRowEdgeCases:
    """Offline, empty email, internal pro, error resilience."""

    def test_offline_returns_none(self, mock_offline):
        from payment import _ensure_user_row
        result = _ensure_user_row("any@test.com")
        assert result is None

    def test_empty_email_returns_none(self, mock_supabase_client):
        from payment import _ensure_user_row
        result = _ensure_user_row("")
        assert result is None

    def test_whitespace_email_returns_none(self, mock_supabase_client):
        from payment import _ensure_user_row
        result = _ensure_user_row("   ")
        assert result is None

    def test_insert_failure_returns_none(self, mock_supabase_client):
        """If Supabase insert throws, return None (don't crash)."""
        from payment import _ensure_user_row

        mock_supabase_client._select_result.data = []
        mock_supabase_client.insert.side_effect = RuntimeError("boom")

        result = _ensure_user_row("fail@test.com")
        assert result is None

    def test_internal_pro_email_gets_pro_plan(self, mock_supabase_client):
        """Internal pro emails should get plan=pro, limit=100."""
        from payment import _ensure_user_row

        mock_supabase_client._select_result.data = []
        mock_supabase_client._insert_result.data = [
            {"email": "tshaik1990@gmail.com", "plan": "pro",
             "analyses_used": 0, "analyses_limit": 100,
             "created_at": "2026-01-01", "id": 99}
        ]

        result = _ensure_user_row("tshaik1990@gmail.com")

        call_args = mock_supabase_client.insert.call_args
        row = call_args[0][0]
        assert row["plan"] == "pro"
        assert row["analyses_limit"] == 100
        assert result["plan"] == "pro"


# ---------------------------------------------------------------------------
# Integration: verify auth flow calls _ensure_user_row
# ---------------------------------------------------------------------------

class TestRenderSidebarAccessCallsEnsureRow:
    """Through AppTest, verify the auth path reaches _ensure_user_row."""

    def test_verify_otp_calls_ensure_user_row(self, monkeypatch):
        """After successful OTP verify, _ensure_user_row must be called."""
        import payment
        if not getattr(payment, "REQUIRE_AUTH", True):
            pytest.skip("Beta mode — OTP verify flow is skipped")
        from streamlit.testing.v1 import AppTest

        calls = []

        class AuthResponse:
            session = object()
            user = type("User", (), {"id": "uuid-123"})()

        monkeypatch.setattr(payment, "_supabase_offline", lambda: False)
        monkeypatch.setattr(payment, "send_otp", lambda email: True)
        monkeypatch.setattr(payment, "verify_otp", lambda email, token: AuthResponse())
        monkeypatch.setattr(payment, "get_user", lambda email: {
            "email": email, "plan": "free", "analyses_used": 0,
            "analyses_limit": 5, "id": 1, "created_at": "2026-01-01",
        })
        monkeypatch.setattr(payment, "load_auth", lambda: None)
        monkeypatch.setattr(payment, "save_auth", lambda email: None)
        monkeypatch.setattr(payment, "clear_auth", lambda: None)

        # Patch _ensure_user_row to record calls
        def _record_ensure(email, user_id=None):
            calls.append({"email": email, "user_id": user_id})
            return {"email": email, "plan": "free", "analyses_used": 0,
                    "analyses_limit": 5, "id": 99, "created_at": "2026-01-01",
                    "authenticated": True, "internal_pro": False}

        monkeypatch.setattr(payment, "_ensure_user_row", _record_ensure)

        at = AppTest.from_file("app.py")
        at.run(timeout=60)

        # Go through full OTP flow
        at.text_input(key="_email_input").set_value("verify@test.com").run()
        at.button(key="send_otp_button").click().run()
        at.text_input(key="_otp_input").set_value("123456").run()
        at.button(key="verify_otp_button").click().run()

        assert len(calls) >= 1, \
            "_ensure_user_row was NOT called after OTP verification"
        assert calls[0]["email"] == "verify@test.com"
