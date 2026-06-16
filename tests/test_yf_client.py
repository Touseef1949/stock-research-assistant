"""Unit tests for the resilient yfinance wrapper."""

from __future__ import annotations

import pytest

from yf_client import YFinanceRateLimitError, _is_rate_limit_error


@pytest.mark.parametrize(
    "message,expected",
    [
        ("Too Many Requests", True),
        ("too many requests", True),
        ("Rate limited", True),
        ("429 Client Error", True),
        ("Unauthorized", True),
        ("Forbidden", True),
        ("some random yfinance error", False),
        ("No market data found", False),
    ],
)
def test_is_rate_limit_error_detection(message, expected):
    assert _is_rate_limit_error(Exception(message)) is expected


def test_is_rate_limit_error_status_code_attr():
    class FakeHttpError(Exception):
        status_code = 429
    assert _is_rate_limit_error(FakeHttpError("boom")) is True


def test_yfinance_rate_limit_error_is_a_type():
    err = YFinanceRateLimitError("rate limited")
    assert str(err) == "rate limited"
    assert isinstance(err, Exception)
