"""Critical gap tests — rate-limit, fallback, exception paths not yet covered.

Run: pytest tests/test_critical_gaps.py -v
"""

from unittest.mock import MagicMock, patch, PropertyMock
import pytest

from yf_client import (
    YFinanceRateLimitError,
    _is_rate_limit_error,
    _call_with_retry,
    ticker_info,
    ticker_history,
    search_quotes,
)


# ═══════════════════════════════════════════════════════════════════
# _call_with_retry — retry/backoff + exception propagation
# ═══════════════════════════════════════════════════════════════════

class TestCallWithRetry:
    """Exercise every branch in _call_with_retry."""

    def test_success_on_first_attempt(self):
        fn = MagicMock(return_value="ok")
        assert _call_with_retry(fn, "test op") == "ok"
        assert fn.call_count == 1

    def test_non_rate_limit_error_raised_immediately(self):
        """Non-rate-limit exception must propagate — not retried."""
        fn = MagicMock(side_effect=ValueError("bad data"))
        with pytest.raises(ValueError, match="bad data"):
            _call_with_retry(fn, "fetch")
        assert fn.call_count == 1  # no retries for non-rate-limit

    def test_rate_limit_detected_via_marker_retries_then_raises(self, monkeypatch):
        """Rate-limit detected by string marker → retry → YFinanceRateLimitError."""
        fn = MagicMock(side_effect=Exception("too many requests"))
        monkeypatch.setattr("yf_client._sleep_with_jitter", lambda _: None)

        with pytest.raises(YFinanceRateLimitError, match="rate limit exceeded"):
            _call_with_retry(fn, "fetch")

        # 1 attempt + _MAX_RETRIES retries = _MAX_RETRIES + 1
        assert fn.call_count == 5  # _MAX_RETRIES=4, so 5 total calls

    def test_rate_limit_detected_via_429_status(self, monkeypatch):
        """Rate-limit detected by status_code=429 → retry."""
        exc = Exception("generic error")
        exc.status_code = 429
        fn = MagicMock(side_effect=exc)
        monkeypatch.setattr("yf_client._sleep_with_jitter", lambda _: None)

        with pytest.raises(YFinanceRateLimitError):
            _call_with_retry(fn, "fetch")
        assert fn.call_count == 5

    def test_rate_limit_detected_via_cause_chain(self, monkeypatch):
        """Rate-limit detected via __cause__ chain → retry."""
        root = Exception("too many requests")
        exc = Exception("outer")
        exc.__cause__ = root
        fn = MagicMock(side_effect=exc)
        monkeypatch.setattr("yf_client._sleep_with_jitter", lambda _: None)

        with pytest.raises(YFinanceRateLimitError):
            _call_with_retry(fn, "fetch")
        assert fn.call_count == 5

    def test_yfinance_rate_limit_error_re_raised_immediately(self):
        """YFinanceRateLimitError from fn() → re-raised without retry."""
        fn = MagicMock(side_effect=YFinanceRateLimitError("explicit"))
        with pytest.raises(YFinanceRateLimitError, match="explicit"):
            _call_with_retry(fn, "fetch")
        assert fn.call_count == 1


# ═══════════════════════════════════════════════════════════════════
# ticker_info — guard + fetch + exception branches
# ═══════════════════════════════════════════════════════════════════

class TestTickerInfo:
    def test_returns_empty_dict_when_yf_is_none(self, monkeypatch):
        monkeypatch.setattr("yf_client.yf", None)
        assert ticker_info("SBIN.NS") == {}

    def test_returns_info_dict_on_success(self, monkeypatch):
        mock_ticker = MagicMock()
        mock_ticker.info = {"marketCap": 500000}
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setattr("yf_client.yf", mock_yf)

        result = ticker_info("SBIN.NS")
        assert result["marketCap"] == 500000

    def test_rate_limit_raises_yfinance_rate_limit_error(self, monkeypatch):
        """_fetch wraps rate-limit → YFinanceRateLimitError → _call_with_retry re-raises."""
        exc = Exception("too many requests")
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = exc
        monkeypatch.setattr("yf_client.yf", mock_yf)

        with pytest.raises(YFinanceRateLimitError):
            ticker_info("SBIN.NS")

    def test_non_rate_limit_propagates(self, monkeypatch):
        """Non-rate-limit exception → propagated."""
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = ValueError("bad symbol")
        monkeypatch.setattr("yf_client.yf", mock_yf)

        with pytest.raises(ValueError, match="bad symbol"):
            ticker_info("SBIN.NS")


# ═══════════════════════════════════════════════════════════════════
# ticker_history — guard + fetch + exception branches
# ═══════════════════════════════════════════════════════════════════

class TestTickerHistory:
    def test_returns_none_when_yf_is_none(self, monkeypatch):
        monkeypatch.setattr("yf_client.yf", None)
        assert ticker_history("SBIN.NS") is None

    def test_returns_empty_when_history_is_empty(self, monkeypatch):
        mock_ticker = MagicMock()
        mock_ticker.history.return_value.empty = True
        mock_yf = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        monkeypatch.setattr("yf_client.yf", mock_yf)
        monkeypatch.setattr("yf_client._fresh_session", MagicMock())

        result = ticker_history("SBIN.NS")
        assert result.empty is True

    def test_rate_limit_raises_yfinance_rate_limit_error(self, monkeypatch):
        exc = Exception("rate limited")
        mock_yf = MagicMock()
        mock_yf.Ticker.side_effect = exc
        monkeypatch.setattr("yf_client.yf", mock_yf)

        with pytest.raises(YFinanceRateLimitError):
            ticker_history("SBIN.NS")


# ═══════════════════════════════════════════════════════════════════
# search_quotes — guard + exception branches
# ═══════════════════════════════════════════════════════════════════

class TestSearchQuotes:
    def test_returns_empty_list_when_yf_is_none(self, monkeypatch):
        monkeypatch.setattr("yf_client.yf", None)
        assert search_quotes("SBIN") == []

    def test_returns_empty_list_when_yf_has_no_search(self, monkeypatch):
        mock_yf = MagicMock(spec=[])
        monkeypatch.setattr("yf_client.yf", mock_yf)
        assert search_quotes("SBIN") == []

    def test_returns_quotes_list_on_success(self, monkeypatch):
        mock_result = MagicMock()
        mock_result.quotes = [{"symbol": "SBIN.NS", "name": "State Bank"}]
        mock_yf = MagicMock()
        mock_yf.Search.return_value = mock_result
        monkeypatch.setattr("yf_client.yf", mock_yf)

        result = search_quotes("SBIN")
        assert len(result) == 1
        assert result[0]["symbol"] == "SBIN.NS"

    def test_rate_limit_raises_yfinance_rate_limit_error(self, monkeypatch):
        exc = Exception("too many requests")
        mock_yf = MagicMock()
        mock_yf.Search.side_effect = exc
        monkeypatch.setattr("yf_client.yf", mock_yf)

        with pytest.raises(YFinanceRateLimitError):
            search_quotes("SBIN")


# ═══════════════════════════════════════════════════════════════════
# _fresh_session — requests-is-None guard
# ═══════════════════════════════════════════════════════════════════

class TestFreshSession:
    def test_returns_none_when_requests_is_none(self, monkeypatch):
        monkeypatch.setattr("yf_client.requests", None)
        from yf_client import _fresh_session
        assert _fresh_session() is None


# ═══════════════════════════════════════════════════════════════════
# logic.py — _search_yfinance (just fixed), _validate_ticker gaps
# ═══════════════════════════════════════════════════════════════════

class TestSearchYfinance:
    """The rate-limit bug fix: _search_yfinance now catches all exceptions."""

    def test_search_quotes_rate_limit_returns_empty(self, monkeypatch):
        """When yfinance rate-limits, _search_yfinance returns empty dict."""
        from yf_client import YFinanceRateLimitError

        def raise_rate_limit(*_a, **_kw):
            raise YFinanceRateLimitError("rate limited")

        monkeypatch.setattr("logic.search_quotes", raise_rate_limit)

        from logic import _search_yfinance
        result = _search_yfinance("SBIN")
        assert result == {"symbol": "", "name": "", "source": "unknown"}

    def test_search_quotes_generic_exception_returns_empty(self, monkeypatch):
        """Any exception in search_quotes → graceful empty return."""
        monkeypatch.setattr("logic.search_quotes",
                            MagicMock(side_effect=RuntimeError("crash")))

        from logic import _search_yfinance
        result = _search_yfinance("TCS")
        assert result["symbol"] == ""
        assert result["source"] == "unknown"


class TestValidateTicker:
    """_validate_ticker exception paths."""

    def test_yf_none_returns_false(self, monkeypatch):
        monkeypatch.setattr("logic.yf", None)
        from logic import _validate_ticker
        assert _validate_ticker("SBIN.NS") is False

    def test_exception_returns_false(self, monkeypatch):
        monkeypatch.setattr("logic.ticker_history",
                            MagicMock(side_effect=RuntimeError("boom")))
        from logic import _validate_ticker
        assert _validate_ticker("SBIN.NS") is False


# ═══════════════════════════════════════════════════════════════════
# app.py — load_market_data fallback chain
# ═══════════════════════════════════════════════════════════════════

class TestLoadMarketDataFallback:
    """Test the fallback chain functions directly (bypass @st.cache_data)."""

    def test_yf_none_goes_to_screener_directly(self, monkeypatch):
        """When yfinance not installed, skip straight to screener fallback."""
        monkeypatch.setattr("app.yf", None)
        monkeypatch.setattr("app.fetch_screener_financials",
                            lambda _: {"success": True,
                                       "data": {"ratios": {"current_price": 800, "market_cap": 500000}}})
        monkeypatch.setattr("app._current_price_from_web_sources", lambda _: 800)

        from app import _market_data_from_screener
        result = _market_data_from_screener("SBIN.NS")
        assert result["price"] == 800
        assert result["source"] == "screener_fallback"

    def test_screener_falls_back_to_web_search(self, monkeypatch):
        """Screener returns success=False → web search fallback."""
        monkeypatch.setattr("app.fetch_screener_financials",
                            lambda _: {"success": False, "warnings": ["blocked"]})
        monkeypatch.setattr("app._current_price_from_web_sources", lambda _: 102)

        from app import _market_data_from_screener
        result = _market_data_from_screener("SBIN.NS")
        assert result["price"] == 102
        assert result["source"] == "web_search_fallback"

    def test_all_layers_fail_raises_honest_error(self, monkeypatch):
        """All three layers fail → honest error, not Yahoo-only message."""
        monkeypatch.setattr("app.fetch_screener_financials",
                            lambda _: {"success": False, "warnings": ["blocked"]})
        monkeypatch.setattr("app._current_price_from_web_sources", lambda _: None)

        from app import _market_data_from_screener
        with pytest.raises(RuntimeError) as exc_info:
            _market_data_from_screener("SBIN.NS")
        msg = str(exc_info.value).lower()
        assert "screener" in msg or "web" in msg or "all" in msg
