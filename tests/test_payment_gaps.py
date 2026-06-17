import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

import payment
from payment import (
    PRO_REPORT_LIMIT,
    _ensure_user_row,
    _internal_pro_payload,
    _is_internal_pro_email,
    _normalize_email,
    clear_auth,
    get_user,
    load_auth,
    save_auth,
    send_otp,
    verify_otp,
)


@pytest.fixture(autouse=True)
def isolated_session_state(monkeypatch):
    monkeypatch.setattr(payment.st, "session_state", {})


@pytest.fixture
def offline_auth_file(tmp_path, monkeypatch):
    auth_file = tmp_path / "sra_auth.json"
    monkeypatch.setattr(payment, "AUTH_FILE", auth_file)
    monkeypatch.setattr(payment, "_supabase_offline", lambda: True)
    return auth_file


def chainable_supabase():
    sb = MagicMock()
    sb.table.return_value = sb
    sb.select.return_value = sb
    sb.eq.return_value = sb
    sb.limit.return_value = sb
    sb.insert.return_value = sb
    sb.update.return_value = sb
    return sb


def test_normalize_email_trims_lowercases_and_handles_empty():
    assert _normalize_email("  USER@Example.COM  ") == "user@example.com"
    assert _normalize_email("") == ""
    assert _normalize_email(None) == ""


def test_save_auth_offline_writes_to_temp_file(offline_auth_file):
    save_auth("  USER@Example.COM  ")

    assert offline_auth_file.exists()
    data = json.loads(offline_auth_file.read_text(encoding="utf-8"))
    assert data["email"] == "user@example.com"
    assert datetime.fromisoformat(data["verified_at"]).tzinfo is not None


def test_load_auth_expired_file_returns_none_and_cleans_up(offline_auth_file):
    old_verified_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    offline_auth_file.write_text(
        json.dumps({"email": "old@example.com", "verified_at": old_verified_at}),
        encoding="utf-8",
    )

    assert load_auth() is None
    assert not offline_auth_file.exists()


def test_clear_auth_offline_deletes_file(offline_auth_file):
    save_auth("clear@example.com")
    assert offline_auth_file.exists()

    clear_auth()

    assert not offline_auth_file.exists()


def test_is_internal_pro_email_true_for_internal_false_for_gmail():
    assert _is_internal_pro_email(" TSHAIK1990@GMAIL.COM ") is True
    assert _is_internal_pro_email("someone@gmail.com") is False


def test_internal_pro_payload_returns_unlimited_pro_payload():
    payload = _internal_pro_payload(" TSHAIK1990@GMAIL.COM ", analyses_used=7)

    assert payload == {
        "id": None,
        "email": "tshaik1990@gmail.com",
        "plan": "pro",
        "analyses_used": 7,
        "analyses_limit": PRO_REPORT_LIMIT,
        "created_at": None,
        "authenticated": True,
        "internal_pro": True,
    }


def test_get_user_when_supabase_unavailable_returns_local_mock_user(monkeypatch):
    monkeypatch.setattr(payment, "get_supabase_admin", lambda: None)

    user = get_user("free@example.com")

    assert user is not None
    assert user.email == "mock@local"
    assert user.authenticated is False


def test_send_otp_valid_email_uses_supabase_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(payment, "get_supabase_client", lambda: client)

    assert send_otp("  USER@Example.COM  ") is True
    client.auth.sign_in_with_otp.assert_called_once_with({"email": "user@example.com"})


def test_send_otp_invalid_email_or_missing_client_returns_false(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(payment, "get_supabase_client", lambda: client)

    assert send_otp("   ") is False
    client.auth.sign_in_with_otp.assert_not_called()

    monkeypatch.setattr(payment, "get_supabase_client", lambda: None)
    assert send_otp("user@example.com") is False


def test_ensure_user_row_create_path(monkeypatch):
    sb = chainable_supabase()
    created_row = {
        "id": 42,
        "email": "new@example.com",
        "plan": "free",
        "analyses_used": 0,
        "analyses_limit": 5,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    sb.execute.return_value = MagicMock(data=[created_row])
    monkeypatch.setattr(payment, "get_supabase_admin", lambda: sb)
    monkeypatch.setattr(payment, "get_user", lambda email: None)
    monkeypatch.setattr(payment, "_now_iso", lambda: created_row["created_at"])

    result = _ensure_user_row("  NEW@Example.COM  ")

    sb.table.assert_called_with("users")
    sb.insert.assert_called_once()
    inserted = sb.insert.call_args.args[0]
    assert inserted == {
        "email": "new@example.com",
        "plan": "free",
        "analyses_used": 0,
        "analyses_limit": 5,
        "created_at": created_row["created_at"],
    }
    assert result["email"] == "new@example.com"
    assert result["plan"] == "free"


def test_ensure_user_row_update_path_for_internal_pro(monkeypatch):
    sb = chainable_supabase()
    sb.execute.return_value = MagicMock(data=[])
    existing = {
        "id": 7,
        "email": "tshaik1990@gmail.com",
        "plan": "free",
        "analyses_used": 3,
        "analyses_limit": 5,
        "created_at": "2026-01-01T00:00:00+00:00",
        "authenticated": True,
        "internal_pro": True,
    }
    monkeypatch.setattr(payment, "get_supabase_admin", lambda: sb)
    monkeypatch.setattr(payment, "get_user", lambda email: existing)

    result = _ensure_user_row(" TSHAIK1990@GMAIL.COM ")

    sb.update.assert_called_once_with({"plan": "pro", "analyses_limit": PRO_REPORT_LIMIT})
    sb.eq.assert_called_with("email", "tshaik1990@gmail.com")
    assert result["plan"] == "pro"
    assert result["analyses_limit"] == PRO_REPORT_LIMIT
    sb.insert.assert_not_called()


def test_verify_otp_valid_token_uses_supabase_client(monkeypatch):
    client = MagicMock()
    response = MagicMock()
    client.auth.verify_otp.return_value = response
    monkeypatch.setattr(payment, "get_supabase_client", lambda: client)

    assert verify_otp(" USER@Example.COM ", " 123456 ") is response
    client.auth.verify_otp.assert_called_once_with(
        {"email": "user@example.com", "token": "123456", "type": "email"}
    )


def test_verify_otp_invalid_email_or_token_returns_none(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(payment, "get_supabase_client", lambda: client)

    assert verify_otp("", "123456") is None
    assert verify_otp("user@example.com", "   ") is None
    client.auth.verify_otp.assert_not_called()

    monkeypatch.setattr(payment, "get_supabase_client", lambda: None)
    assert verify_otp("user@example.com", "123456") is None
