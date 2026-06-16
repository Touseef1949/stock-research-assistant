"""Tests for yf_client.py — rate limiting, retry, session management.

Run: pytest tests/test_yf_client.py -v
"""

from unittest.mock import MagicMock, patch

import pytest
import requests as requests_lib

from yf_client import (
    YFinanceRateLimitError,
    _is_rate_limit_error,
    _fresh_session,
    _sleep_with_jitter,
    is_rate_limit_error,
    _MAX_RETRIES,
    _BASE_DELAY,
    _MAX_DELAY,
    _USER_AGENTS,
)


# ── YFinanceRateLimitError ──
def test_rate_limit_error_is_exception():
    err = YFinanceRateLimitError("test")
    assert isinstance(err, Exception)


def test_rate_limit_error_message():
    err = YFinanceRateLimitError("rate limited!")
    assert "rate limited" in str(err)


def test_rate_limit_error_can_be_caught():
    try:
        raise YFinanceRateLimitError("test")
    except YFinanceRateLimitError as e:
        assert str(e) == "test"


# ── _is_rate_limit_error ──
@pytest.mark.parametrize("msg", [
    "too many requests",
    "rate limit exceeded",
    "rate limited",
    "429",
    "unauthorized",
    "blocked",
    "forbidden",
    "yfratelimiterror: something",
])
def test_is_rate_limit_error_detects_marker(msg):
    exc = Exception(msg)
    assert _is_rate_limit_error(exc) is True


def test_is_rate_limit_error_by_status_code():
    exc = Exception("some error")
    exc.status_code = 429
    assert _is_rate_limit_error(exc) is True

    exc2 = Exception("other")
    exc2.status_code = 403
    assert _is_rate_limit_error(exc2) is True

    exc3 = Exception("other")
    exc3.status_code = 401
    assert _is_rate_limit_error(exc3) is True


def test_is_rate_limit_error_normal_exception():
    exc = Exception("connection timeout")
    assert _is_rate_limit_error(exc) is False


def test_is_rate_limit_error_value_error():
    exc = ValueError("invalid data")
    assert _is_rate_limit_error(exc) is False


def test_is_rate_limit_error_chained():
    """Detect rate limits through exception chaining."""
    root = Exception("too many requests")
    outer = Exception("wrapper")
    outer.__cause__ = root
    assert _is_rate_limit_error(outer) is True


def test_is_rate_limit_error_context_chain():
    """Detect through __context__ as well."""
    root = Exception("429")
    outer = Exception("wrapper")
    outer.__context__ = root
    assert _is_rate_limit_error(outer) is True


def test_is_rate_limit_error_case_insensitive():
    exc = Exception("TOO MANY REQUESTS")
    assert _is_rate_limit_error(exc) is True


# ── is_rate_limit_error (public) ──
def test_public_is_rate_limit_error():
    assert is_rate_limit_error(Exception("rate limit")) is True
    assert is_rate_limit_error(Exception("normal error")) is False


# ── _fresh_session ──
def test_fresh_session_returns_session():
    session = _fresh_session()
    assert isinstance(session, requests_lib.Session)


def test_fresh_session_has_user_agent():
    session = _fresh_session()
    assert "User-Agent" in session.headers


def test_fresh_session_has_security_headers():
    session = _fresh_session()
    assert session.headers.get("DNT") == "1"
    assert "Sec-Fetch-Dest" in session.headers


def test_fresh_sessions_are_distinct():
    s1 = _fresh_session()
    s2 = _fresh_session()
    assert s1 is not s2


# ── _sleep_with_jitter ──
def test_sleep_with_jitter_calls_time_sleep(monkeypatch):
    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("yf_client.time.sleep", fake_sleep)

    _sleep_with_jitter(2)  # attempt 2 → delay = min(3*4, 30) = 12, jitter 0-12

    assert len(sleep_calls) == 1
    delay = sleep_calls[0]
    assert 0 <= delay <= 12.0


def test_sleep_with_jitter_max_capped(monkeypatch):
    """Attempt 4 would give 3*16=48 but capped at 30."""
    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("yf_client.time.sleep", fake_sleep)

    _sleep_with_jitter(5)  # attempt 5 → min(3*32, 30) = 30

    assert len(sleep_calls) == 1
    assert sleep_calls[0] <= 30.0


def test_sleep_with_jitter_first_attempt(monkeypatch):
    """Attempt 0 → delay = min(3*1, 30) = 3, jitter 0-3."""
    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("yf_client.time.sleep", fake_sleep)

    _sleep_with_jitter(0)

    assert 0 <= sleep_calls[0] <= 3.0


# ── Constants ──
def test_max_retries():
    assert _MAX_RETRIES == 4


def test_base_delay():
    assert _BASE_DELAY == 3.0


def test_max_delay():
    assert _MAX_DELAY == 30.0


def test_user_agents_not_empty():
    assert len(_USER_AGENTS) >= 2
    for agent in _USER_AGENTS:
        assert "Mozilla" in agent


def test_user_agents_are_diverse():
    """Should have agents for different platforms."""
    agents_lower = [a.lower() for a in _USER_AGENTS]
    platforms = 0
    if any("mac" in a for a in agents_lower):
        platforms += 1
    if any("windows" in a for a in agents_lower):
        platforms += 1
    if any("linux" in a for a in agents_lower):
        platforms += 1
    assert platforms >= 2, "Should cover at least 2 platforms"
