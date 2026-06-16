"""Tests for payment.py — auth, plans, user management, rate limits.

Run: pytest tests/test_payment.py -v
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import payment
from payment import (
    _normalize_email,
    _is_placeholder,
    _is_internal_pro_email,
    _internal_pro_payload,
    _user_payload,
    _now_iso,
    _read_attr,
    _auth_user_id,
    _MockUser,
    save_auth,
    load_auth,
    clear_auth,
    FREE_REPORT_LIMIT,
    PRO_REPORT_LIMIT,
    TIER_LIMITS,
    TIER_PRICES_PAISE,
    INTERNAL_PRO_EMAILS,
)


# ── _normalize_email ──
def test_normalize_email_lowercases():
    assert _normalize_email("Test@Email.com") == "test@email.com"


def test_normalize_email_strips_whitespace():
    assert _normalize_email("  user@dom.com  ") == "user@dom.com"


def test_normalize_email_empty():
    assert _normalize_email("") == ""


def test_normalize_email_none():
    assert _normalize_email(None) == ""


# ── _is_placeholder ──
def test_is_placeholder_empty():
    assert _is_placeholder("") is True


def test_is_placeholder_xxxxx():
    assert _is_placeholder("xxxxx") is True


def test_is_placeholder_your_project():
    assert _is_placeholder("your-project.supabase.co") is True


def test_is_placeholder_valid_url():
    assert _is_placeholder("https://abc123.supabase.co") is False


def test_is_placeholder_real_key():
    assert _is_placeholder("eyJhbGciOiJIUzI1NiJ9.actually-real") is False


# ── Tier constants ──
def test_free_report_limit():
    assert FREE_REPORT_LIMIT == 5


def test_pro_report_limit():
    assert PRO_REPORT_LIMIT == 100


def test_tier_limits_has_free_and_pro():
    assert TIER_LIMITS["free"] == 5
    assert TIER_LIMITS["pro"] == 100


def test_tier_prices():
    assert TIER_PRICES_PAISE["free"] == 0
    assert TIER_PRICES_PAISE["pro"] == 19_900  # ₹199


# ── Internal pro ──
def test_is_internal_pro_email():
    assert _is_internal_pro_email("tshaik1990@gmail.com") is True
    assert _is_internal_pro_email("TSHAIK1990@GMAIL.COM") is True
    assert _is_internal_pro_email("other@gmail.com") is False


def test_internal_pro_email_set():
    assert "tshaik1990@gmail.com" in INTERNAL_PRO_EMAILS


def test_internal_pro_payload():
    payload = _internal_pro_payload("tshaik1990@gmail.com")
    assert payload["plan"] == "pro"
    assert payload["analyses_limit"] == PRO_REPORT_LIMIT
    assert payload["authenticated"] is True
    assert payload["internal_pro"] is True


# ── _user_payload ──
def test_user_payload_free():
    row = {"email": "free@test.com", "plan": "free", "analyses_used": 2}
    result = _user_payload(row)
    assert result["plan"] == "free"
    assert result["analyses_limit"] == FREE_REPORT_LIMIT
    assert result["analyses_used"] == 2


def test_user_payload_pro():
    row = {"email": "pro@test.com", "plan": "pro", "analyses_used": 50}
    result = _user_payload(row)
    assert result["plan"] == "pro"
    assert result["analyses_limit"] == PRO_REPORT_LIMIT


def test_user_payload_internal_overrides_to_pro():
    """Internal pro email always gets pro regardless of DB value."""
    row = {"email": "tshaik1990@gmail.com", "plan": "free", "analyses_used": 5}
    result = _user_payload(row)
    assert result["plan"] == "pro"
    assert result["analyses_limit"] == PRO_REPORT_LIMIT
    assert result["internal_pro"] is True


# ── _now_iso ──
def test_now_iso_returns_valid_iso():
    iso_str = _now_iso()
    dt = datetime.fromisoformat(iso_str)
    assert isinstance(dt, datetime)


def test_now_iso_is_utc():
    iso_str = _now_iso()
    assert "+00:00" in iso_str or iso_str.endswith("Z")


# ── _read_attr ──
def test_read_attr_from_dict():
    d = {"key": "value"}
    assert _read_attr(d, "key") == "value"
    assert _read_attr(d, "missing", "default") == "default"


def test_read_attr_from_object():
    class Obj:
        key = "val"

    assert _read_attr(Obj(), "key") == "val"
    assert _read_attr(Obj(), "missing", 42) == 42


def test_read_attr_none():
    assert _read_attr(None, "anything", "fallback") == "fallback"


# ── _auth_user_id ──
def test_auth_user_id_from_user():
    class MockUser:
        id = "uid_123"

    class MockResponse:
        user = MockUser()

    assert _auth_user_id(MockResponse()) == "uid_123"


def test_auth_user_id_from_session():
    class MockUser:
        id = "uid_456"

    class MockSession:
        user = MockUser()

    class MockResponse:
        session = MockSession()

    assert _auth_user_id(MockResponse()) == "uid_456"


def test_auth_user_id_dict():
    resp = {"user": {"id": "uid_789"}}
    assert _auth_user_id(resp) == "uid_789"


def test_auth_user_id_none():
    assert _auth_user_id(None) is None


# ── _MockUser ──
def test_mock_user_defaults():
    u = _MockUser()
    assert u.plan == "free"
    assert u.analyses_used == 0
    assert u.analyses_limit == FREE_REPORT_LIMIT
    assert u.email == "mock@local"
    assert u.authenticated is False


def test_mock_user_attributes_are_accessible():
    u = _MockUser()
    # Test the attribute-access pattern used in require_payment()
    assert hasattr(u, "plan")
    assert hasattr(u, "analyses_used")


# ── Auth file I/O (tmp_path) ──
@pytest.fixture
def auth_tmp_path(tmp_path, monkeypatch):
    """Redirect AUTH_FILE to tmp_path for isolated tests."""
    test_file = tmp_path / "sra_auth.json"
    monkeypatch.setattr(payment, "AUTH_FILE", test_file)
    yield test_file
    # Cleanup
    test_file.unlink(missing_ok=True)


def test_save_and_load_auth_roundtrip(auth_tmp_path):
    email = "roundtrip@test.com"
    save_auth(email)
    assert auth_tmp_path.exists()

    loaded = load_auth()
    assert loaded == email


def test_load_auth_no_file(auth_tmp_path):
    assert not auth_tmp_path.exists()
    assert load_auth() is None


def test_clear_auth(auth_tmp_path):
    save_auth("clear@test.com")
    assert auth_tmp_path.exists()
    clear_auth()
    assert not auth_tmp_path.exists()


def test_clear_auth_when_missing(auth_tmp_path):
    """clear_auth should not raise when file doesn't exist."""
    clear_auth()  # no exception


def test_load_auth_expired(auth_tmp_path):
    """Auth older than 7 days should be treated as expired."""
    old_date = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    auth_tmp_path.write_text(
        json.dumps({"email": "old@test.com", "verified_at": old_date}),
        encoding="utf-8",
    )
    assert load_auth() is None
    assert not auth_tmp_path.exists()  # file should be deleted


def test_load_auth_corrupted(auth_tmp_path):
    """Corrupted auth file should be cleaned up."""
    auth_tmp_path.write_text("not valid json", encoding="utf-8")
    assert load_auth() is None


def test_save_auth_empty_email(auth_tmp_path):
    """Empty email should not create an auth file."""
    save_auth("")
    assert not auth_tmp_path.exists()


# ── _valid_supabase_config (with env mocking) ──
def test_valid_supabase_config_missing(monkeypatch):
    """Should return False when env vars are not set."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    # This will also try st.secrets, which we can't easily mock here
    # but the env fallback should return empty
    assert payment._valid_supabase_config("SUPABASE_KEY") is False
