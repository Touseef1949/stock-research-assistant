"""Complete coverage gap tests — yf_client 100%, logic 95%+.

Run: pytest tests/test_full_coverage.py -v
"""

from unittest.mock import MagicMock, patch
import pytest
import pandas as pd
import numpy as np

from yf_client import (
    YFinanceRateLimitError,
    ticker_history,
    search_quotes,
)


# ═══════════════════════════════════════════════════════════════════
# yf_client.py — lines 164, 181 (non-rate-limit raise in fetch)
# ═══════════════════════════════════════════════════════════════════

class TestYfClientFinalGaps:
    """Last 2 uncovered lines in yf_client.py (98% → 100%)."""

    def test_ticker_history_non_rate_limit_propagates(self, monkeypatch):
        """Non-rate-limit exception in ticker_history._fetch → re-raised."""
        exc = TypeError("unhashable type")
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = exc
        monkeypatch.setattr("yf_client.yf", mock_yf)
        monkeypatch.setattr("yf_client._fresh_session", MagicMock())

        with pytest.raises(TypeError, match="unhashable"):
            ticker_history("TEST.NS")

    def test_search_quotes_non_rate_limit_propagates(self, monkeypatch):
        """Non-rate-limit exception in search_quotes._fetch → re-raised."""
        exc = OSError("connection refused")
        mock_yf = MagicMock()
        mock_yf.Search.side_effect = exc
        monkeypatch.setattr("yf_client.yf", mock_yf)

        with pytest.raises(OSError, match="connection refused"):
            search_quotes("TEST")


# ═══════════════════════════════════════════════════════════════════
# logic.py — 84% → 95%+
# ═══════════════════════════════════════════════════════════════════

class TestLogicHelpers:
    """Cover display_symbol, scoring helpers, and resolve_ticker paths."""

    def test_display_symbol_strips_ns(self):
        from logic import display_symbol
        assert display_symbol("SBIN.NS") == "SBIN"

    def test_display_symbol_no_ns_passthrough(self):
        from logic import display_symbol
        assert display_symbol("TCS") == "TCS"


class TestResolveTickerGaps:
    """resolve_ticker KNOWN_TICKERS fallback + validation path."""

    def test_resolve_ticker_via_known_map(self, monkeypatch):
        """Ticker found in KNOWN_TICKERS map → returns mapped result."""
        monkeypatch.setattr("logic.yf", None)  # simulate no yfinance
        from logic import resolve_ticker
        # SBIN should be in KNOWN_TICKERS
        result = resolve_ticker("SBIN")
        assert result["symbol"] == "SBIN.NS"
        assert result["source"] == "map"

    def test_resolve_ticker_validates_then_map(self, monkeypatch):
        """_validate_ticker fails → falls back to KNOWN_TICKERS map."""
        monkeypatch.setattr("logic._validate_ticker", lambda _: False)
        from logic import resolve_ticker
        result = resolve_ticker("SBIN")
        assert result["symbol"] == "SBIN.NS"

    def test_resolve_ticker_non_alpha_empty(self, monkeypatch):
        """Non-alphanumeric input returns empty."""
        from logic import resolve_ticker
        result = resolve_ticker("")
        assert result["symbol"] == ""


class TestSearchYfinanceScoring:
    """Cover quote scoring logic in _search_yfinance (lines 149-171)."""

    def test_search_returns_nse_quote(self, monkeypatch):
        """NS quote scores higher than non-NS."""
        mock_quotes = [
            {"symbol": "SBIN.NS", "exchange": "NSE", "name": "State Bank"},
            {"symbol": "SBIN", "exchange": "NYSE", "name": "SBI NY"},
        ]
        monkeypatch.setattr("logic.search_quotes", lambda q: mock_quotes)
        from logic import _search_yfinance
        result = _search_yfinance("SBIN")
        assert result["symbol"] == "SBIN.NS"

    def test_search_returns_empty_when_no_quotes(self, monkeypatch):
        monkeypatch.setattr("logic.search_quotes", lambda q: [])
        from logic import _search_yfinance
        result = _search_yfinance("UNKNOWN")
        assert result["symbol"] == ""
        assert result["source"] == "unknown"


class TestValidateTickerSuccess:
    """Cover _validate_ticker success path (line 139)."""

    def test_validate_ticker_success(self, monkeypatch):
        mock_hist = MagicMock()
        mock_hist.empty = False
        monkeypatch.setattr("logic.ticker_history", lambda *a, **kw: mock_hist)
        from logic import _validate_ticker
        assert _validate_ticker("SBIN.NS") is True

    def test_validate_ticker_empty_history(self, monkeypatch):
        mock_hist = MagicMock()
        mock_hist.empty = True
        monkeypatch.setattr("logic.ticker_history", lambda *a, **kw: mock_hist)
        from logic import _validate_ticker
        assert _validate_ticker("SBIN.NS") is False


# ═══════════════════════════════════════════════════════════════════
# logic.py — compute_rsi, compute_macd, clamp_score helpers
# ═══════════════════════════════════════════════════════════════════

class TestRSI:
    def test_rsi_basic(self):
        from logic import compute_rsi
        closes = pd.Series([48, 49, 50, 49, 48, 49, 50, 51, 50, 49,
                            50, 51, 52, 51, 50, 51, 52, 53, 54, 53,
                            52, 53, 54, 55, 56, 55, 54, 53, 54, 55])
        rsi = compute_rsi(closes)
        assert rsi is not None
        last = rsi.dropna().iloc[-1]
        assert 0 <= last <= 100

    def test_rsi_all_up(self):
        from logic import compute_rsi
        closes = pd.Series(range(1, 50), dtype=float) + 50  # all positive deltas
        rsi = compute_rsi(closes)
        non_null = rsi.dropna()
        if len(non_null) > 0:
            assert non_null.iloc[-1] > 50

    def test_rsi_all_down(self):
        from logic import compute_rsi
        closes = pd.Series(range(50, 0, -1), dtype=float) + 50
        rsi = compute_rsi(closes)
        non_null = rsi.dropna()
        if len(non_null) > 0:
            assert non_null.iloc[-1] < 50

    def test_rsi_too_short(self):
        from logic import compute_rsi
        closes = pd.Series([100, 101])
        rsi = compute_rsi(closes)
        assert rsi is not None


class TestMACD:
    def test_macd_basic(self):
        from logic import compute_macd
        closes = pd.Series(range(1, 100), dtype=float)
        macd, signal = compute_macd(closes)
        assert macd is not None
        assert signal is not None

    def test_macd_too_short(self):
        from logic import compute_macd
        closes = pd.Series(range(1, 20), dtype=float)
        macd, signal = compute_macd(closes)
        assert macd is not None


class TestClampScore:
    def test_clamp_below_1(self):
        from logic import clamp_score
        assert clamp_score(-5.0) == 1.0

    def test_clamp_above_10(self):
        from logic import clamp_score
        assert clamp_score(15.0) == 10.0

    def test_clamp_in_range(self):
        from logic import clamp_score
        assert clamp_score(7.5) == 7.5

    def test_clamp_at_boundary(self):
        from logic import clamp_score
        assert clamp_score(1.0) == 1.0
        assert clamp_score(10.0) == 10.0


class TestToNseSymbol:
    def test_appends_ns(self):
        from logic import to_nse_symbol
        result = to_nse_symbol("SBIN")
        assert ".NS" in result
        assert "SBIN" in result

    def test_no_double_ns(self):
        from logic import to_nse_symbol
        result = to_nse_symbol("SBIN.NS")
        assert result.count(".NS") == 1


class TestSafeFloat:
    def test_valid_float(self):
        from logic import safe_float
        assert safe_float("3.14") == 3.14

    def test_none_returns_none(self):
        from logic import safe_float
        assert safe_float(None) is None

    def test_invalid_returns_none(self):
        from logic import safe_float
        assert safe_float("abc") is None

    def test_int_string(self):
        from logic import safe_float
        assert safe_float("42") == 42.0

    def test_already_float(self):
        from logic import safe_float
        assert safe_float(3.14) == 3.14
