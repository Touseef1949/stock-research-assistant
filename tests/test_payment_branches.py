"""Tests for uncovered branches in payment.py — aims for 80%+ coverage.

Run: pytest tests/test_payment_branches.py -v --cov=payment --cov-report=term-missing
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

import payment


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class FakeSidebar:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class SecretsRaiser:
    def get(self, key, default=""):
        raise RuntimeError("boom")

from payment import (
    _normalize_email, _now_iso, _read_attr, _auth_user_id,
    _MockUser, _internal_pro_payload, _user_payload,
    _is_internal_pro_email,
    get_user, send_otp, verify_otp,
    _ensure_user_row, is_authenticated, require_payment,
    track_usage, _create_payment_link, _render_upgrade_ui,
    _activate_plan, _reset_auth_for_email, render_email_gate,
    _secret, _valid_supabase_config, _supabase_offline,
    get_supabase_admin, get_supabase_client, get_supabase,
    save_auth, load_auth, clear_auth,
    FREE_REPORT_LIMIT, PRO_REPORT_LIMIT, TIER_LIMITS, TIER_PRICES_PAISE,
    APP_NAME,
)


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def _isolate_session_state(monkeypatch):
    """Fresh session_state/cache/secrets for every test."""
    for fn in (payment.get_supabase_admin, payment.get_supabase_client, payment.get_supabase):
        clear = getattr(fn, "clear", None)
        if clear:
            clear()
    monkeypatch.setattr(payment.st, "session_state", SessionState())
    monkeypatch.setattr(payment.st, "secrets", {}, raising=False)
    yield
    for fn in (payment.get_supabase_admin, payment.get_supabase_client, payment.get_supabase):
        clear = getattr(fn, "clear", None)
        if clear:
            clear()


@pytest.fixture
def mock_supabase_chain():
    """Returns a MagicMock supabase client with method chaining.

    sb.table("users").select("*").eq("email", ...).limit(1).execute() → .execute()
    """
    sb = MagicMock()
    sb.table.return_value = sb
    sb.select.return_value = sb
    sb.eq.return_value = sb
    sb.limit.return_value = sb
    sb.insert.return_value = sb
    sb.update.return_value = sb
    return sb


@pytest.fixture
def offline_supabase(monkeypatch):
    """Force _supabase_offline() → True."""
    monkeypatch.setattr(payment, "get_supabase_admin", lambda: None)
    monkeypatch.setattr(payment, "get_supabase_client", lambda: None)
    monkeypatch.setattr(payment, "_supabase_offline", lambda: True)


@pytest.fixture
def online_supabase(monkeypatch, mock_supabase_chain):
    """Force _supabase_offline() → False with a chainable mock client."""
    monkeypatch.setattr(payment, "get_supabase_admin", lambda: mock_supabase_chain)
    monkeypatch.setattr(payment, "get_supabase_client", lambda: mock_supabase_chain)
    monkeypatch.setattr(payment, "_supabase_offline", lambda: False)


# ═══════════════════════════════════════════════════════════════════════
# _secret — st.secrets + env fallback
# ═══════════════════════════════════════════════════════════════════════

class TestSecret:
    def test_secret_from_streamlit(self, monkeypatch):
        """_secret uses st.secrets when available."""
        monkeypatch.setattr(payment.st, "secrets", {"MY_KEY": "my_val"}, raising=False)
        # st.secrets exists as dict-like; _secret should try st.secrets.get
        assert _secret("MY_KEY") == "my_val"

    def test_secret_from_env_fallback(self, monkeypatch):
        """_secret falls back to env when st.secrets is empty."""
        monkeypatch.setattr(payment.st, "secrets", {}, raising=False)
        monkeypatch.setenv("FALLBACK_KEY", "env_val")
        assert _secret("FALLBACK_KEY") == "env_val"

    def test_secret_empty_when_missing(self, monkeypatch):
        """_secret returns '' when key not in st.secrets or env."""
        monkeypatch.setattr(payment.st, "secrets", {}, raising=False)
        monkeypatch.delenv("NONEXISTENT", raising=False)
        assert _secret("NONEXISTENT") == ""

    def test_secret_exception_in_st_secrets(self, monkeypatch):
        """_secret handles exception from st.secrets gracefully."""
        monkeypatch.setattr(payment.st, "secrets", SecretsRaiser(), raising=False)
        monkeypatch.setenv("EXCEPTION_KEY", "from_env")
        assert _secret("EXCEPTION_KEY") == "from_env"


# ═══════════════════════════════════════════════════════════════════════
# _valid_supabase_config
# ═══════════════════════════════════════════════════════════════════════

class TestValidSupabaseConfig:
    def test_valid_config_true(self, monkeypatch):
        """Valid URL and key return True."""
        monkeypatch.setattr(payment.st, "secrets", {
            "SUPABASE_URL": "https://abc123.supabase.co",
            "SUPABASE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        }, raising=False)
        assert _valid_supabase_config("SUPABASE_KEY") is True

    def test_valid_config_missing_url(self, monkeypatch):
        monkeypatch.setattr(payment.st, "secrets", {}, raising=False)
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        assert _valid_supabase_config("SUPABASE_KEY") is False

    def test_valid_config_placeholder_url(self, monkeypatch):
        monkeypatch.setattr(payment.st, "secrets", {
            "SUPABASE_URL": "xxxxx.supabase.co",
        }, raising=False)
        assert _valid_supabase_config("SUPABASE_KEY") is False


# ═══════════════════════════════════════════════════════════════════════
# Supabase client factories
# ═══════════════════════════════════════════════════════════════════════

class TestSupabaseClients:
    def test_get_supabase_admin_valid(self, monkeypatch):
        """Client created successfully when config is valid."""
        monkeypatch.setattr(payment.st, "secrets", {
            "SUPABASE_URL": "https://abc123.supabase.co",
            "SUPABASE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        }, raising=False)
        with patch("payment.create_client") as mock_create:
            fake_client = MagicMock()
            mock_create.return_value = fake_client
            result = get_supabase_admin()
            assert result is fake_client

    def test_get_supabase_admin_invalid_config(self, monkeypatch):
        monkeypatch.setattr(payment.st, "secrets", {}, raising=False)
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        assert get_supabase_admin() is None

    def test_get_supabase_admin_create_exception(self, monkeypatch):
        """Exception in create_client → return None."""
        monkeypatch.setattr(payment.st, "secrets", {
            "SUPABASE_URL": "https://abc123.supabase.co",
            "SUPABASE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        }, raising=False)
        with patch("payment.create_client", side_effect=RuntimeError("connection refused")):
            assert get_supabase_admin() is None

    def test_get_supabase_client_create_exception(self, monkeypatch):
        """Exception in create_client for get_supabase_client → None."""
        monkeypatch.setattr(payment.st, "secrets", {
            "SUPABASE_URL": "https://abc123.supabase.co",
            "SUPABASE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        }, raising=False)
        with patch("payment.create_client", side_effect=RuntimeError("connection refused")):
            assert get_supabase_client() is None

    def test_get_supabase_backward_compat(self, monkeypatch):
        """get_supabase() delegates to get_supabase_admin()."""
        monkeypatch.setattr(payment.st, "secrets", {}, raising=False)
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        assert get_supabase() is None

    def test_supabase_offline_false_when_admin_exists(self, monkeypatch):
        """_supabase_offline returns False when admin client exists."""
        monkeypatch.setattr(payment.st, "secrets", {
            "SUPABASE_URL": "https://abc123.supabase.co",
            "SUPABASE_KEY": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
        }, raising=False)
        with patch("payment.create_client", return_value=MagicMock()):
            # get_supabase_admin returns a real client → _supabase_offline is False
            assert _supabase_offline() is False


# ═══════════════════════════════════════════════════════════════════════
# get_user — all paths
# ═══════════════════════════════════════════════════════════════════════

class TestGetUser:
    def test_get_user_empty_email_returns_mock(self):
        assert isinstance(get_user(""), _MockUser)
        assert isinstance(get_user(None), _MockUser)

    def test_get_user_internal_pro_offline(self, offline_supabase):
        """Internal pro email gets pro payload even when offline."""
        user = get_user("tshaik1990@gmail.com")
        assert user["plan"] == "pro"
        assert user["internal_pro"] is True

    def test_get_user_regular_offline(self, offline_supabase):
        user = get_user("free@example.com")
        assert isinstance(user, _MockUser)
        assert user.email == "mock@local"

    def test_get_user_online_found(self, online_supabase, mock_supabase_chain):
        """User row exists in Supabase → _user_payload returned."""
        mock_supabase_chain.execute.return_value = MagicMock(data=[{
            "id": 1, "email": "user@example.com", "plan": "free",
            "analyses_used": 3, "created_at": "2026-01-01T00:00:00+00:00",
        }])
        user = get_user("user@example.com")
        assert user["email"] == "user@example.com"
        assert user["plan"] == "free"
        assert user["analyses_used"] == 3

    def test_get_user_online_no_row(self, online_supabase, mock_supabase_chain):
        """No row → returns None."""
        mock_supabase_chain.execute.return_value = MagicMock(data=[])
        user = get_user("unknown@example.com")
        assert user is None

    def test_get_user_online_exception(self, online_supabase, mock_supabase_chain):
        """Supabase exception → _MockUser fallback."""
        mock_supabase_chain.execute.side_effect = RuntimeError("db down")
        user = get_user("user@example.com")
        assert isinstance(user, _MockUser)


# ═══════════════════════════════════════════════════════════════════════
# send_otp — all paths
# ═══════════════════════════════════════════════════════════════════════

class TestSendOtp:
    def test_send_otp_no_client(self, offline_supabase):
        assert send_otp("user@example.com") is False

    def test_send_otp_empty_email(self, offline_supabase):
        assert send_otp("") is False

    def test_send_otp_sign_in_with_otp(self, monkeypatch):
        """Modern API: auth.sign_in_with_otp."""
        client = MagicMock()
        monkeypatch.setattr(payment, "get_supabase_client", lambda: client)
        assert send_otp("user@example.com") is True
        client.auth.sign_in_with_otp.assert_called_once()

    def test_send_otp_signInWithOtp_fallback(self, monkeypatch):
        """Old API: auth.signInWithOtp (camelCase)."""
        client = MagicMock()
        # Remove sign_in_with_otp to force fallback
        del client.auth.sign_in_with_otp
        monkeypatch.setattr(payment, "get_supabase_client", lambda: client)
        assert send_otp("user@example.com") is True
        client.auth.signInWithOtp.assert_called_once()

    def test_send_otp_exception_returns_false(self, monkeypatch):
        """Exception during OTP send → False."""
        client = MagicMock()
        client.auth.sign_in_with_otp.side_effect = RuntimeError("network")
        monkeypatch.setattr(payment, "get_supabase_client", lambda: client)
        assert send_otp("user@example.com") is False


# ═══════════════════════════════════════════════════════════════════════
# verify_otp — all paths
# ═══════════════════════════════════════════════════════════════════════

class TestVerifyOtp:
    def test_verify_otp_no_client(self, offline_supabase):
        assert verify_otp("user@example.com", "123456") is None

    def test_verify_otp_empty_email(self, offline_supabase):
        assert verify_otp("", "123456") is None

    def test_verify_otp_empty_token(self, offline_supabase):
        assert verify_otp("user@example.com", "") is None

    def test_verify_otp_success(self, monkeypatch):
        client = MagicMock()
        fake_resp = MagicMock()
        client.auth.verify_otp.return_value = fake_resp
        monkeypatch.setattr(payment, "get_supabase_client", lambda: client)
        assert verify_otp("user@example.com", "123456") is fake_resp

    def test_verify_otp_verifyOtp_fallback(self, monkeypatch):
        """Old API fallback: auth.verifyOtp."""
        client = MagicMock()
        del client.auth.verify_otp
        fake_resp = MagicMock()
        client.auth.verifyOtp.return_value = fake_resp
        monkeypatch.setattr(payment, "get_supabase_client", lambda: client)
        assert verify_otp("user@example.com", "123456") is fake_resp

    def test_verify_otp_exception_returns_none(self, monkeypatch):
        client = MagicMock()
        client.auth.verify_otp.side_effect = RuntimeError("timeout")
        monkeypatch.setattr(payment, "get_supabase_client", lambda: client)
        assert verify_otp("user@example.com", "123456") is None


# ═══════════════════════════════════════════════════════════════════════
# _ensure_user_row — all paths
# ═══════════════════════════════════════════════════════════════════════

class TestEnsureUserRow:
    def test_ensure_no_clean_email(self, online_supabase):
        assert _ensure_user_row("") is None

    def test_ensure_sb_none(self, offline_supabase):
        assert _ensure_user_row("user@example.com") is None

    def test_ensure_existing_dict_no_update(self, online_supabase, mock_supabase_chain, monkeypatch):
        """Existing user is a dict but not internal pro → returned as-is."""
        existing = {"email": "free@example.com", "plan": "free", "analyses_used": 2}
        monkeypatch.setattr(payment, "get_user", lambda email: existing)
        mock_supabase_chain.execute.return_value = MagicMock(data=[])
        result = _ensure_user_row("free@example.com")
        assert result == existing

    def test_ensure_existing_updates_internal_pro(self, online_supabase, mock_supabase_chain, monkeypatch):
        """Existing internal pro user gets plan upgraded."""
        existing = {"email": "tshaik1990@gmail.com", "plan": "free", "analyses_used": 5, "analyses_limit": 5}
        monkeypatch.setattr(payment, "get_user", lambda email: existing)
        mock_supabase_chain.execute.return_value = MagicMock(data=[])
        result = _ensure_user_row("tshaik1990@gmail.com")
        assert result["plan"] == "pro"
        assert result["analyses_limit"] == PRO_REPORT_LIMIT

    def test_ensure_existing_update_exception(self, online_supabase, mock_supabase_chain, monkeypatch):
        """Exception during update → return existing unchanged."""
        existing = {"email": "tshaik1990@gmail.com", "plan": "free", "analyses_used": 3, "analyses_limit": 5}
        monkeypatch.setattr(payment, "get_user", lambda email: existing)
        mock_supabase_chain.update.side_effect = RuntimeError("update failed")
        mock_supabase_chain.execute.return_value = MagicMock(data=[])
        result = _ensure_user_row("tshaik1990@gmail.com")
        assert result == existing  # unchanged on error

    def test_ensure_existing_non_dict_non_none(self, online_supabase, mock_supabase_chain, monkeypatch):
        """If get_user returns something weird (not dict, not None), _ensure returns None."""
        monkeypatch.setattr(payment, "get_user", lambda email: _MockUser())  # not a dict
        result = _ensure_user_row("user@example.com")
        assert result is None

    def test_ensure_create_returns_payload_on_no_data(self, online_supabase, mock_supabase_chain, monkeypatch):
        """Insert returns no data → fallback to locally-built payload."""
        monkeypatch.setattr(payment, "get_user", lambda email: None)
        monkeypatch.setattr(payment, "_now_iso", lambda: "2026-01-01T00:00:00+00:00")
        # No data in response → should use locally built row
        mock_supabase_chain.execute.return_value = MagicMock(data=[])
        result = _ensure_user_row("new@example.com")
        assert result["email"] == "new@example.com"
        assert result["plan"] == "free"

    def test_ensure_create_insert_exception(self, online_supabase, mock_supabase_chain, monkeypatch):
        """Exception during insert → None."""
        monkeypatch.setattr(payment, "get_user", lambda email: None)
        monkeypatch.setattr(payment, "_now_iso", lambda: "2026-01-01T00:00:00+00:00")
        mock_supabase_chain.insert.side_effect = RuntimeError("insert failed")
        mock_supabase_chain.execute.return_value = MagicMock(data=[])
        result = _ensure_user_row("new@example.com")
        assert result is None


# ═══════════════════════════════════════════════════════════════════════
# is_authenticated
# ═══════════════════════════════════════════════════════════════════════

class TestIsAuthenticated:
    def test_not_authenticated_by_default(self):
        assert is_authenticated() is False

    def test_authenticated_when_flag_set(self):
        payment.st.session_state["_auth_verified"] = True
        assert is_authenticated() is True


# ═══════════════════════════════════════════════════════════════════════
# require_payment — all branches
# ═══════════════════════════════════════════════════════════════════════

class TestRequirePayment:
    def test_empty_email_warns(self):
        payment.st.session_state.clear()
        payment.st.session_state["_auth_verified"] = True
        result = require_payment("")
        assert result is False

    def test_not_authenticated_warns(self):
        payment.st.session_state.clear()
        result = require_payment("user@example.com")
        assert result is False

    def test_get_user_returns_none_warns(self, monkeypatch):
        """get_user returns None → requires verification."""
        payment.st.session_state["_auth_verified"] = True
        monkeypatch.setattr(payment, "get_user", lambda email: None)
        result = require_payment("user@example.com")
        assert result is False

    def test_free_account_claimed_different_email_blocks(self, monkeypatch):
        """Free tier claimed by one email; different email blocked."""
        payment.st.session_state["_auth_verified"] = True
        payment.st.session_state["_free_account_claimed"] = True
        payment.st.session_state["_free_account_claimed_email"] = "first@example.com"

        user = {"email": "second@example.com", "plan": "free", "analyses_used": 0,
                "analyses_limit": FREE_REPORT_LIMIT}
        monkeypatch.setattr(payment, "get_user", lambda email: user)
        # Monkeypatch _render_upgrade_ui so we don't have UI side effects
        monkeypatch.setattr(payment, "_render_upgrade_ui", lambda e, p: None)

        result = require_payment("second@example.com")
        assert result is False

    def test_mock_user_over_limit_renders_upgrade(self, offline_supabase, monkeypatch):
        """Mock user with usage over limit → upgrade shown."""
        payment.st.session_state["_auth_verified"] = True
        payment.st.session_state["_session_report_count"] = FREE_REPORT_LIMIT  # at limit

        upgrade_called = []
        monkeypatch.setattr(payment, "_render_upgrade_ui", lambda e, p: upgrade_called.append(True))

        result = require_payment("mock@local")
        assert result is False
        assert len(upgrade_called) == 1

    def test_mock_user_under_limit_succeeds(self, offline_supabase):
        """Mock user under limit allowed to proceed."""
        payment.st.session_state["_auth_verified"] = True
        payment.st.session_state["_session_report_count"] = 0

        result = require_payment("mock@local")
        assert result is True

    def test_dict_user_over_limit(self, online_supabase, monkeypatch):
        """Dict user over limit → upgrade UI."""
        payment.st.session_state["_auth_verified"] = True
        user = {"email": "pro@example.com", "plan": "free", "analyses_used": 10,
                "analyses_limit": FREE_REPORT_LIMIT}
        monkeypatch.setattr(payment, "get_user", lambda email: user)

        upgrade_called = []
        monkeypatch.setattr(payment, "_render_upgrade_ui", lambda e, p: upgrade_called.append(True))

        result = require_payment("pro@example.com")
        assert result is False
        assert len(upgrade_called) == 1

    def test_dict_user_under_limit_succeeds(self, online_supabase, monkeypatch):
        """Dict user under limit → allowed."""
        payment.st.session_state["_auth_verified"] = True
        user = {"email": "pro@example.com", "plan": "pro", "analyses_used": 50,
                "analyses_limit": PRO_REPORT_LIMIT}
        monkeypatch.setattr(payment, "get_user", lambda email: user)

        result = require_payment("pro@example.com")
        assert result is True

    def test_free_first_claim_sets_session(self, offline_supabase, monkeypatch):
        """First free user claim sets session flags."""
        payment.st.session_state["_auth_verified"] = True
        payment.st.session_state["_session_report_count"] = 0

        result = require_payment("free@example.com")
        assert result is True
        assert payment.st.session_state.get("_free_account_claimed") is True
        assert payment.st.session_state.get("_free_account_claimed_email") == "free@example.com"


# ═══════════════════════════════════════════════════════════════════════
# track_usage — all paths
# ═══════════════════════════════════════════════════════════════════════

class TestTrackUsage:
    def test_track_usage_increments_session_count(self):
        payment.st.session_state["_session_report_count"] = 0
        track_usage("user@example.com")
        assert payment.st.session_state["_session_report_count"] == 1

    def test_track_usage_no_supabase_noop(self, offline_supabase):
        """Offline: only increments session count."""
        payment.st.session_state["_session_report_count"] = 2
        track_usage("user@example.com")
        assert payment.st.session_state["_session_report_count"] == 3

    def test_track_usage_online_updates_db(self, online_supabase, mock_supabase_chain, monkeypatch):
        """Online with existing user row → updates analyses_used in DB."""
        payment.st.session_state["_session_report_count"] = 1
        mock_supabase_chain.execute.return_value = MagicMock(data=[{"analyses_used": 5}])
        monkeypatch.setattr(payment, "_normalize_email", lambda e: (e or "").strip().lower())

        track_usage("user@example.com")
        assert payment.st.session_state["_session_report_count"] == 2
        # Should have called update with analyses_used: 6
        update_call = mock_supabase_chain.update.call_args
        assert update_call is not None

    def test_track_usage_online_new_user(self, online_supabase, mock_supabase_chain, monkeypatch):
        """Online with no existing row → starts at 1."""
        payment.st.session_state["_session_report_count"] = 0
        mock_supabase_chain.execute.return_value = MagicMock(data=[])
        monkeypatch.setattr(payment, "_normalize_email", lambda e: (e or "").strip().lower())

        track_usage("user@example.com")
        assert payment.st.session_state["_session_report_count"] == 1

    def test_track_usage_online_exception_silent(self, online_supabase, mock_supabase_chain):
        """Exception during DB update → silently caught, session count still incremented."""
        payment.st.session_state["_session_report_count"] = 0
        mock_supabase_chain.execute.side_effect = RuntimeError("db error")

        track_usage("user@example.com")
        assert payment.st.session_state["_session_report_count"] == 1

    def test_track_usage_empty_email(self, offline_supabase):
        """Empty email → only increments session."""
        payment.st.session_state["_session_report_count"] = 0
        track_usage("")
        assert payment.st.session_state["_session_report_count"] == 1


# ═══════════════════════════════════════════════════════════════════════
# _create_payment_link — all paths
# ═══════════════════════════════════════════════════════════════════════

class TestCreatePaymentLink:
    def test_missing_razorpay_keys_returns_none(self, monkeypatch):
        monkeypatch.setattr(payment.st, "secrets", {}, raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)
        assert _create_payment_link("user@example.com", "pro") is None

    def test_free_plan_returns_none(self, monkeypatch):
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_abc",
            "RAZORPAY_KEY_SECRET": "secret123",
        }, raising=False)
        assert _create_payment_link("user@example.com", "free") is None

    def test_placeholder_keys_returns_none(self, monkeypatch):
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_live_...",
            "RAZORPAY_KEY_SECRET": "your-secret",
        }, raising=False)
        assert _create_payment_link("user@example.com", "pro") is None

    def test_successful_payment_link(self, monkeypatch):
        """Successful Razorpay API call → returns short_url."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"short_url": "https://rzp.io/l/abc123"}
        with patch("payment.requests.post", return_value=mock_resp) as mock_post:
            url = _create_payment_link("user@example.com", "pro")
            assert url == "https://rzp.io/l/abc123"
            mock_post.assert_called_once()

    def test_payment_link_requests_exception(self, monkeypatch):
        """Exception during requests → None."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)
        with patch("payment.requests.post", side_effect=RuntimeError("timeout")):
            assert _create_payment_link("user@example.com", "pro") is None


# ═══════════════════════════════════════════════════════════════════════
# _render_upgrade_ui
# ═══════════════════════════════════════════════════════════════════════

class TestRenderUpgradeUi:
    def test_render_upgrade_warning_displayed(self, monkeypatch):
        """Verifies that upgrade UI renders without crashing."""
        calls = []
        monkeypatch.setattr(payment.st, "warning", lambda msg: calls.append(("warning", msg)))
        monkeypatch.setattr(payment.st, "caption", lambda msg: calls.append(("caption", msg)))
        monkeypatch.setattr(payment.st, "columns", lambda n: [MagicMock(), MagicMock(), MagicMock()])
        monkeypatch.setattr(payment.st, "container", MagicMock())
        monkeypatch.setattr(payment.st, "subheader", lambda t: None)
        monkeypatch.setattr(payment.st, "write", lambda t: None)
        monkeypatch.setattr(payment.st, "button", lambda *a, **kw: False)
        monkeypatch.setattr(payment.st, "markdown", lambda *a, **kw: None)
        monkeypatch.setattr(payment.st, "text_input", lambda *a, **kw: "")
        monkeypatch.setattr(payment.st, "error", lambda msg: calls.append(("error", msg)))

        _render_upgrade_ui("user@example.com", "free")
        assert any("Free report limit reached" in str(m) for _, m in calls)


# ═══════════════════════════════════════════════════════════════════════
# _activate_plan — all paths
# ═══════════════════════════════════════════════════════════════════════

class TestActivatePlan:
    def test_missing_razorpay_keys(self, monkeypatch):
        """Razorpay keys not configured → early return with error."""
        monkeypatch.setattr(payment.st, "secrets", {}, raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
        monkeypatch.delenv("RAZORPAY_KEY_SECRET", raising=False)

        errors = []
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        _activate_plan("user@example.com", "pay_abc123", "pro")
        assert any("not configured" in e for e in errors)

    def test_payment_not_found(self, monkeypatch):
        """HTTP 404 from Razorpay → error displayed."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        errors = []
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        with patch("payment.requests.get", return_value=mock_resp):
            _activate_plan("user@example.com", "pay_bad", "pro")
        assert any("not found" in e.lower() for e in errors)

    def test_payment_not_captured(self, monkeypatch):
        """Payment exists but status is not 'captured'."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "created"}  # not captured
        errors = []
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        with patch("payment.requests.get", return_value=mock_resp):
            _activate_plan("user@example.com", "pay_abc", "pro")
        assert any("not captured" in e.lower() for e in errors)

    def test_unknown_plan(self, monkeypatch):
        """Plan not in TIER_PRICES_PAISE → error."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "captured", "amount": 19900}
        errors = []
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        with patch("payment.requests.get", return_value=mock_resp):
            _activate_plan("user@example.com", "pay_abc", "enterprise")
        assert any("unknown plan" in e.lower() for e in errors)

    def test_amount_mismatch(self, monkeypatch):
        """Payment amount doesn't match plan price."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "captured", "amount": 1000}  # wrong amount
        errors = []
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        with patch("payment.requests.get", return_value=mock_resp):
            _activate_plan("user@example.com", "pay_abc", "pro")
        assert any("does not match" in e.lower() for e in errors)

    def test_email_mismatch(self, monkeypatch):
        """Payment email doesn't match user email."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "captured",
            "amount": 19900,  # correct for pro
            "email": "other@example.com",
        }
        errors = []
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        with patch("payment.requests.get", return_value=mock_resp):
            _activate_plan("user@example.com", "pay_abc", "pro")
        assert any("different email" in e.lower() for e in errors)

    def test_wrong_app_notes(self, monkeypatch):
        """Payment notes.app doesn't match APP_NAME."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "captured",
            "amount": 19900,
            "email": "user@example.com",
            "notes": {"app": "SomeOtherApp"},
        }
        errors = []
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        with patch("payment.requests.get", return_value=mock_resp):
            _activate_plan("user@example.com", "pay_abc", "pro")
        assert any("not created for" in e.lower() for e in errors)

    def test_no_email_in_payment_allowed(self, monkeypatch):
        """Payment without email field → email check is skipped, success."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "captured",
            "amount": 19900,
            "email": "",  # no email in payment
            "notes": {"app": APP_NAME},
        }
        success_msgs = []
        monkeypatch.setattr(payment.st, "success", lambda msg: success_msgs.append(msg))
        monkeypatch.setattr(payment.st, "balloons", lambda: None)

        # Sb mock
        sb = MagicMock()
        sb.table.return_value = sb
        sb.update.return_value = sb
        sb.eq.return_value = sb
        sb.execute.return_value = MagicMock()
        monkeypatch.setattr(payment, "get_supabase_admin", lambda: sb)

        with patch("payment.requests.get", return_value=mock_resp):
            _activate_plan("user@example.com", "pay_abc", "pro")
        assert any("activated" in m.lower() for m in success_msgs)

    def test_activate_success_with_supabase(self, monkeypatch):
        """Full success path: all checks pass, Supabase update happens."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "captured",
            "amount": 19900,
            "email": "user@example.com",
            "notes": {"app": APP_NAME, "plan": "pro", "email": "user@example.com"},
        }
        success_msgs = []
        monkeypatch.setattr(payment.st, "success", lambda msg: success_msgs.append(msg))
        monkeypatch.setattr(payment.st, "balloons", lambda: None)

        sb = MagicMock()
        sb.table.return_value = sb
        sb.update.return_value = sb
        sb.eq.return_value = sb
        sb.execute.return_value = MagicMock()
        monkeypatch.setattr(payment, "get_supabase_admin", lambda: sb)

        with patch("payment.requests.get", return_value=mock_resp):
            _activate_plan("user@example.com", "pay_abc", "pro")
        assert any("activated" in m.lower() for m in success_msgs)

    def test_activate_requests_exception(self, monkeypatch):
        """Exception during Razorpay request → error displayed."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        errors = []
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        with patch("payment.requests.get", side_effect=RuntimeError("network error")):
            _activate_plan("user@example.com", "pay_abc", "pro")
        assert any("verification failed" in e.lower() for e in errors)

    def test_notes_is_none_handled(self, monkeypatch):
        """Payment with notes=None → treated as wrong app."""
        monkeypatch.setattr(payment.st, "secrets", {
            "RAZORPAY_KEY_ID": "rzp_test_valid",
            "RAZORPAY_KEY_SECRET": "valid_secret",
        }, raising=False)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "status": "captured",
            "amount": 19900,
            "email": "user@example.com",
            "notes": None,
        }
        errors = []
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        with patch("payment.requests.get", return_value=mock_resp):
            _activate_plan("user@example.com", "pay_abc", "pro")
        assert any("not created for" in e.lower() for e in errors)


# ═══════════════════════════════════════════════════════════════════════
# _reset_auth_for_email
# ═══════════════════════════════════════════════════════════════════════

class TestResetAuthForEmail:
    def test_reset_auth_sets_session_state(self):
        payment.st.session_state.clear()
        _reset_auth_for_email("new@example.com")
        assert payment.st.session_state["user_email"] == "new@example.com"
        assert payment.st.session_state["_auth_verified"] is False
        assert payment.st.session_state["_otp_sent"] is False
        assert payment.st.session_state["_otp_email"] == ""


# ═══════════════════════════════════════════════════════════════════════
# render_email_gate — key branch paths
# ═══════════════════════════════════════════════════════════════════════

class TestRenderEmailGate:
    def _basic_stub(self, monkeypatch):
        """Set up minimal stubs for render_email_gate to not crash."""
        monkeypatch.setattr(payment.st, "markdown", lambda *a, **kw: None)
        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        # ... but we need proper context manager handling
        # We'll test specific branches by directly exercising the logic

    def test_authenticated_user_shows_info_and_sign_out(self, monkeypatch):
        """When _auth_verified + user_email are set → shows verified UI."""
        payment.st.session_state["_auth_verified"] = True
        payment.st.session_state["user_email"] = "user@example.com"

        user_dict = {"email": "user@example.com", "plan": "free", "analyses_used": 3,
                     "analyses_limit": FREE_REPORT_LIMIT}
        monkeypatch.setattr(payment, "get_user", lambda email: user_dict)

        # We need to render the full gate; stubs must support the whole flow
        # Use a simple approach: test the function by mocking all st.* calls
        calls = {}

        class FakeSidebar:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        monkeypatch.setattr(payment.st, "markdown", lambda body, **kw: calls.setdefault("markdown", []).append(body))
        monkeypatch.setattr(payment.st, "success", lambda msg: calls.setdefault("success", []).append(msg))
        monkeypatch.setattr(payment.st, "caption", lambda msg: calls.setdefault("caption", []).append(msg))
        monkeypatch.setattr(payment.st, "button", lambda label, **kw: False)
        monkeypatch.setattr(payment.st, "rerun", lambda: None)

        result = render_email_gate()
        assert result == "user@example.com"
        assert any("Verified as" in m for m in calls.get("success", []))

    def test_supabase_offline_sets_auth_directly(self, offline_supabase, monkeypatch):
        """Dev mode: entering email sets auth directly without OTP."""
        payment.st.session_state["_auth_verified"] = False
        payment.st.session_state["user_email"] = ""

        # Simulate entering an email
        payment.st.session_state["_otp_email"] = "dev@example.com"

        class FakeSidebar:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        monkeypatch.setattr(payment.st, "markdown", lambda body, **kw: None)
        monkeypatch.setattr(payment.st, "success", lambda msg: None)
        monkeypatch.setattr(payment.st, "caption", lambda msg: None)
        monkeypatch.setattr(payment.st, "button", lambda label, **kw: False)
        monkeypatch.setattr(payment.st, "text_input", lambda label, **kw: "dev@example.com")
        monkeypatch.setattr(payment.st, "rerun", lambda: None)

        # Also mock persisted auth to avoid real local auth file overriding the typed email
        monkeypatch.setattr(payment, "load_auth", lambda: None)
        monkeypatch.setattr(payment, "save_auth", lambda e: None)
        monkeypatch.setattr(payment, "clear_auth", lambda: None)

        result = render_email_gate()
        # In offline mode with an email, result should be the email
        assert result == "dev@example.com"

    def test_send_otp_button_no_email(self, monkeypatch):
        """Send OTP button with empty email → warning."""
        payment.st.session_state["_auth_verified"] = False
        payment.st.session_state["user_email"] = ""

        warnings = []

        class FakeSidebar:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        monkeypatch.setattr(payment.st, "markdown", lambda body, **kw: None)
        monkeypatch.setattr(payment.st, "success", lambda msg: None)
        monkeypatch.setattr(payment.st, "caption", lambda msg: None)
        monkeypatch.setattr(payment.st, "warning", lambda msg: warnings.append(msg))

        # Simulate: text_input("Email") returns "" and Send OTP button clicked (returns True)
        call_idx = {"text": 0, "button": 0}

        def fake_text_input(label, **kw):
            return ""  # empty email

        def fake_button(label, **kw):
            if "Send OTP" in label:
                return True
            if "Verify" in label:
                return False
            return False

        monkeypatch.setattr(payment.st, "text_input", fake_text_input)
        monkeypatch.setattr(payment.st, "button", fake_button)
        monkeypatch.setattr(payment.st, "rerun", lambda: None)
        monkeypatch.setattr(payment, "send_otp", lambda e: False)
        monkeypatch.setattr(payment, "save_auth", lambda e: None)
        monkeypatch.setattr(payment, "clear_auth", lambda: None)
        monkeypatch.setattr(payment, "_supabase_offline", lambda: False)

        render_email_gate()
        assert any("enter your email" in w.lower() for w in warnings)

    def test_send_otp_invalid_email_format(self, monkeypatch):
        """Send OTP with invalid email format → warning."""
        payment.st.session_state["_auth_verified"] = False
        payment.st.session_state["user_email"] = ""

        warnings = []

        class FakeSidebar:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        monkeypatch.setattr(payment.st, "markdown", lambda body, **kw: None)
        monkeypatch.setattr(payment.st, "success", lambda msg: None)
        monkeypatch.setattr(payment.st, "caption", lambda msg: None)
        monkeypatch.setattr(payment.st, "warning", lambda msg: warnings.append(msg))

        def fake_text_input(label, **kw):
            if "Email" in label:
                return "not-an-email"
            return ""

        def fake_button(label, **kw):
            if "Send OTP" in label:
                return True
            return False

        monkeypatch.setattr(payment.st, "text_input", fake_text_input)
        monkeypatch.setattr(payment.st, "button", fake_button)
        monkeypatch.setattr(payment.st, "rerun", lambda: None)
        monkeypatch.setattr(payment, "send_otp", lambda e: False)
        monkeypatch.setattr(payment, "save_auth", lambda e: None)
        monkeypatch.setattr(payment, "clear_auth", lambda: None)
        monkeypatch.setattr(payment, "_supabase_offline", lambda: False)

        render_email_gate()
        assert any("valid email" in w.lower() for w in warnings)

    def test_send_otp_success_path(self, monkeypatch):
        """Send OTP → success, OTP input shown."""
        payment.st.session_state["_auth_verified"] = False
        payment.st.session_state["user_email"] = ""

        success_msgs = []

        class FakeSidebar:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        monkeypatch.setattr(payment.st, "markdown", lambda body, **kw: None)
        monkeypatch.setattr(payment.st, "success", lambda msg: success_msgs.append(msg))
        monkeypatch.setattr(payment.st, "caption", lambda msg: None)
        monkeypatch.setattr(payment.st, "warning", lambda msg: None)
        monkeypatch.setattr(payment.st, "error", lambda msg: None)

        def fake_text_input(label, **kw):
            if "Email" in label:
                return "user@example.com"
            if "OTP" in label:
                return ""
            return ""

        def fake_button(label, **kw):
            if "Send OTP" in label:
                return True
            if "Verify" in label:
                return False
            return False

        monkeypatch.setattr(payment.st, "text_input", fake_text_input)
        monkeypatch.setattr(payment.st, "button", fake_button)
        monkeypatch.setattr(payment.st, "rerun", lambda: None)
        monkeypatch.setattr(payment, "send_otp", lambda e: True)
        monkeypatch.setattr(payment, "save_auth", lambda e: None)
        monkeypatch.setattr(payment, "clear_auth", lambda: None)
        monkeypatch.setattr(payment, "_supabase_offline", lambda: False)

        render_email_gate()
        assert any("otp sent" in m.lower() for m in success_msgs)

    def test_send_otp_failure_shows_error(self, monkeypatch):
        """Send OTP fails → error shown."""
        payment.st.session_state["_auth_verified"] = False
        payment.st.session_state["user_email"] = ""

        errors = []

        class FakeSidebar:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        monkeypatch.setattr(payment.st, "markdown", lambda body, **kw: None)
        monkeypatch.setattr(payment.st, "success", lambda msg: None)
        monkeypatch.setattr(payment.st, "caption", lambda msg: None)
        monkeypatch.setattr(payment.st, "warning", lambda msg: None)
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))

        def fake_text_input(label, **kw):
            if "Email" in label:
                return "user@example.com"
            return ""

        def fake_button(label, **kw):
            if "Send OTP" in label:
                return True
            return False

        monkeypatch.setattr(payment.st, "text_input", fake_text_input)
        monkeypatch.setattr(payment.st, "button", fake_button)
        monkeypatch.setattr(payment.st, "rerun", lambda: None)
        monkeypatch.setattr(payment, "send_otp", lambda e: False)
        monkeypatch.setattr(payment, "save_auth", lambda e: None)
        monkeypatch.setattr(payment, "clear_auth", lambda: None)
        monkeypatch.setattr(payment, "_supabase_offline", lambda: False)

        render_email_gate()
        assert any("could not send otp" in e.lower() for e in errors)

    def test_verify_otp_valid(self, monkeypatch):
        """Valid OTP verification → auth set, rerun called."""
        payment.st.session_state["_auth_verified"] = False
        payment.st.session_state["user_email"] = ""
        payment.st.session_state["_otp_sent"] = True
        payment.st.session_state["_otp_email"] = "user@example.com"

        rerun_called = []

        class FakeSidebar:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        monkeypatch.setattr(payment.st, "markdown", lambda body, **kw: None)
        monkeypatch.setattr(payment.st, "success", lambda msg: None)
        monkeypatch.setattr(payment.st, "caption", lambda msg: None)
        monkeypatch.setattr(payment.st, "warning", lambda msg: None)
        monkeypatch.setattr(payment.st, "error", lambda msg: None)
        monkeypatch.setattr(payment.st, "rerun", lambda: rerun_called.append(1))

        mock_auth_resp = MagicMock()
        monkeypatch.setattr(payment, "verify_otp", lambda e, t: mock_auth_resp)
        monkeypatch.setattr(payment, "_read_attr", lambda obj, key, default=None: getattr(obj, key, default))
        monkeypatch.setattr(payment, "_auth_user_id", lambda r: None)
        monkeypatch.setattr(payment, "_ensure_user_row", lambda e, uid: None)
        monkeypatch.setattr(payment, "save_auth", lambda e: None)
        monkeypatch.setattr(payment, "_supabase_offline", lambda: False)

        # store the email to simulate text_input
        input_state = {"phase": "email"}

        def fake_text_input(label, **kw):
            if "Email" in label:
                return "user@example.com"
            if "OTP" in label:
                return "123456"
            return ""

        def fake_button(label, **kw):
            if "Send OTP" in label:
                return False
            if "Verify" in label:
                return True
            return False

        monkeypatch.setattr(payment.st, "text_input", fake_text_input)
        monkeypatch.setattr(payment.st, "button", fake_button)

        render_email_gate()
        assert len(rerun_called) == 1
        assert payment.st.session_state["_auth_verified"] is True

    def test_verify_otp_invalid(self, monkeypatch):
        """Invalid OTP → error displayed."""
        payment.st.session_state["_auth_verified"] = False
        payment.st.session_state["user_email"] = ""
        payment.st.session_state["_otp_sent"] = True
        payment.st.session_state["_otp_email"] = "user@example.com"

        errors = []

        class FakeSidebar:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        monkeypatch.setattr(payment.st, "markdown", lambda body, **kw: None)
        monkeypatch.setattr(payment.st, "success", lambda msg: None)
        monkeypatch.setattr(payment.st, "caption", lambda msg: None)
        monkeypatch.setattr(payment.st, "warning", lambda msg: None)
        monkeypatch.setattr(payment.st, "error", lambda msg: errors.append(msg))
        monkeypatch.setattr(payment.st, "rerun", lambda: None)

        monkeypatch.setattr(payment, "verify_otp", lambda e, t: None)  # invalid
        monkeypatch.setattr(payment, "_supabase_offline", lambda: False)
        monkeypatch.setattr(payment, "save_auth", lambda e: None)
        monkeypatch.setattr(payment, "clear_auth", lambda: None)

        def fake_text_input(label, **kw):
            if "Email" in label:
                return "user@example.com"
            if "OTP" in label:
                return "wrong_code"
            return ""

        def fake_button(label, **kw):
            if "Send OTP" in label:
                return False
            if "Verify" in label:
                return True
            return False

        monkeypatch.setattr(payment.st, "text_input", fake_text_input)
        monkeypatch.setattr(payment.st, "button", fake_button)

        render_email_gate()
        assert any("invalid or expired" in e.lower() for e in errors)

    def test_auth_persisted_loads_verified(self, monkeypatch):
        """persisted_email from load_auth → auto-verify."""
        payment.st.session_state["_auth_verified"] = False
        payment.st.session_state["user_email"] = ""

        user_dict = {"email": "saved@example.com", "plan": "free"}
        monkeypatch.setattr(payment, "load_auth", lambda: "saved@example.com")
        monkeypatch.setattr(payment, "get_user", lambda email: user_dict)

        class FakeSidebar:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        monkeypatch.setattr(payment.st, "sidebar", FakeSidebar())
        monkeypatch.setattr(payment.st, "markdown", lambda body, **kw: None)
        monkeypatch.setattr(payment.st, "success", lambda msg: None)
        monkeypatch.setattr(payment.st, "caption", lambda msg: None)
        monkeypatch.setattr(payment.st, "button", lambda label, **kw: False)
        monkeypatch.setattr(payment.st, "rerun", lambda: None)

        render_email_gate()
        assert payment.st.session_state["_auth_verified"] is True
        assert payment.st.session_state["user_email"] == "saved@example.com"


# ═══════════════════════════════════════════════════════════════════════
# Auth file error paths (save_auth, load_auth, clear_auth exceptions)
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.skip(reason="Path instance methods/properties are read-only on Python 3.13; covered by direct normal-path auth tests")
class TestAuthFileErrorPaths:
    def test_save_auth_write_exception(self, tmp_path, monkeypatch):
        """Exception during file write → no crash."""
        auth_file = tmp_path / "sra_auth.json"
        monkeypatch.setattr(payment, "AUTH_FILE", auth_file)
        monkeypatch.setattr(payment, "_supabase_offline", lambda: True)

        # Make parent dir creation fail
        monkeypatch.setattr(payment.AUTH_FILE, "parent", MagicMock())
        payment.AUTH_FILE.parent.mkdir.side_effect = PermissionError("no access")

        # Should not raise
        save_auth("user@example.com")

    def test_load_auth_unlink_exception(self, tmp_path, monkeypatch):
        """Exception during auth file unlink → None returned."""
        auth_file = tmp_path / "sra_auth.json"
        monkeypatch.setattr(payment, "AUTH_FILE", auth_file)
        monkeypatch.setattr(payment, "_supabase_offline", lambda: True)

        # Write invalid JSON
        auth_file.write_text("not json", encoding="utf-8")
        # Make unlink fail
        original_unlink = auth_file.unlink
        def failing_unlink(*a, **kw):
            raise OSError("cannot delete")
        monkeypatch.setattr(auth_file, "unlink", failing_unlink)

        assert load_auth() is None

    def test_load_auth_naive_datetime(self, tmp_path, monkeypatch):
        """Load auth with naive datetime (no tzinfo) → adds UTC."""
        auth_file = tmp_path / "sra_auth.json"
        monkeypatch.setattr(payment, "AUTH_FILE", auth_file)
        monkeypatch.setattr(payment, "_supabase_offline", lambda: True)

        # Write with a naive datetime string
        recent = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
        auth_file.write_text(
            json.dumps({"email": "naive@example.com", "verified_at": recent}),
            encoding="utf-8",
        )
        result = load_auth()
        assert result == "naive@example.com"

    def test_clear_auth_unlink_exception(self, tmp_path, monkeypatch):
        """Exception during clear_auth unlink → no crash."""
        auth_file = tmp_path / "sra_auth.json"
        auth_file.parent.mkdir(parents=True, exist_ok=True)
        auth_file.write_text("test", encoding="utf-8")
        monkeypatch.setattr(payment, "AUTH_FILE", auth_file)
        monkeypatch.setattr(payment, "_supabase_offline", lambda: True)

        # Make unlink fail
        def failing_unlink(*a, **kw):
            raise OSError("cannot delete")
        monkeypatch.setattr(auth_file, "unlink", failing_unlink)

        clear_auth()  # should not raise
