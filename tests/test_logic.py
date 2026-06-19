"""Tests for logic.py — pure business logic functions.

Run: pytest tests/test_logic.py -v
"""

import pytest
import pandas as pd
import logic
from logic import (
    to_nse_symbol,
    display_symbol,
    clamp_score,
    safe_float,
    money,
    number,
    pct,
    compute_rsi,
    compute_macd,
    local_scores,
    composite_score,
    verdict_for_score,
    parse_score,
    resolve_ticker,
    _normalize_query,
    _search_yfinance,
    _validate_ticker,
)
from yf_client import YFinanceRateLimitError


# ── to_nse_symbol ──
@pytest.mark.parametrize("inp,expected", [
    ("SBIN", "SBIN.NS"),
    ("SBIN.NS", "SBIN.NS"),
    ("sbin", "SBIN.NS"),
    ("  RELIANCE  ", "RELIANCE.NS"),
    ("TCS", "TCS.NS"),
    ("", ""),
    ("   ", ""),
])
def test_to_nse_symbol(inp, expected):
    assert to_nse_symbol(inp) == expected


def test_to_nse_symbol_bse_to_nse():
    """to_nse_symbol always adds .NS suffix unless already present."""
    assert to_nse_symbol("TCS.BO") == "TCS.BO.NS"


# ── display_symbol ──
def test_display_symbol():
    assert display_symbol("SBIN.NS") == "SBIN"
    assert display_symbol("RELIANCE.NS") == "RELIANCE"
    assert display_symbol("TCS") == "TCS"


# ── clamp_score ──
def test_clamp_score():
    assert clamp_score(7.5) == 7.5
    assert clamp_score(15.0) == 10.0
    assert clamp_score(-3.0) == 1.0
    assert clamp_score(0.0) == 1.0
    assert clamp_score(10.0) == 10.0


# ── safe_float ──
def test_safe_float():
    assert safe_float(42) == 42.0
    assert safe_float("3.14") == 3.14
    assert safe_float(None) is None
    assert safe_float(float("nan")) is None


# ── money ──
def test_money():
    assert money(1_500_000_000) == "₹150.00Cr"  # 150 Cr
    assert money(100_000) == "₹100,000"
    assert money(150_000_000_000) == "₹15.00K Cr"  # 15000 Cr
    assert money(None) == "Unavailable"
    assert money(2_500_000) == "₹2,500,000"


# ── number ──
def test_number():
    assert number(1234.5678) == "1,234.57"
    assert number(50, "%") == "50.00%"
    assert number(None) == "Unavailable"


# ── pct ──
def test_pct():
    assert pct(0.156) == "15.60%"
    assert pct(0.0) == "0.00%"
    assert pct(None) == "Unavailable"


# ── compute_rsi ──
def test_compute_rsi():
    prices = [100, 102, 101, 103, 105, 104, 106, 108, 107, 109,
              110, 108, 107, 109, 111, 110, 112, 114, 113, 115]
    close = pd.Series(prices)
    rsi = compute_rsi(close, period=14)
    assert rsi is not None
    assert 0 <= rsi.iloc[-1] <= 100


# ── compute_macd ──
def test_compute_macd():
    prices = list(range(100, 200))
    close = pd.Series(prices)
    macd, signal = compute_macd(close)
    assert len(macd) == len(close)
    assert len(signal) == len(close)


# ── local_scores ──
def test_local_scores():
    fundamentals = {
        "trailing_pe": 18.0,
        "roe": 0.20,
        "debt_to_equity": 45.0,
        "revenue_growth": 0.12,
        "beta": 1.1,
    }
    technicals = {
        "trend": "Bullish",
        "rsi": 55.0,
        "macd": 2.5,
        "macd_signal": 1.8,
        "return_1y_pct": 18.0,
        "max_drawdown_pct": 20.0,
        "volatility_60d_pct": 28.0,
    }
    scores = local_scores(fundamentals, technicals)
    assert "Fundamentals" in scores
    assert "Technicals" in scores
    assert "Sentiment" in scores
    assert "Risk" in scores
    for s in scores.values():
        assert 1.0 <= s <= 10.0


def test_local_scores_bearish():
    fundamentals = {"trailing_pe": 80.0, "roe": 0.03, "debt_to_equity": 200.0,
                    "revenue_growth": -0.05, "beta": 1.8}
    technicals = {"trend": "Bearish", "rsi": 20.0, "macd": -1.0,
                  "macd_signal": -0.5, "return_1y_pct": -25.0,
                  "max_drawdown_pct": 45.0, "volatility_60d_pct": 50.0}
    scores = local_scores(fundamentals, technicals)
    # Poor metrics should produce below-average scores
    assert scores["Fundamentals"] < 5.0
    assert scores["Technicals"] < 5.0


# ── composite_score ──
def test_composite_score():
    scores = {"Fundamentals": 8.0, "Technicals": 7.0, "Sentiment": 6.0, "Risk": 7.5}
    composite = composite_score(scores)
    assert 1.0 <= composite <= 10.0
    # Weighted: 8*0.32 + 7*0.26 + 6*0.18 + 7.5*0.24 = 7.26
    assert abs(composite - 7.26) < 0.15


def test_composite_score_missing():
    scores = {"Fundamentals": 7.0, "Technicals": 6.0}
    composite = composite_score(scores)
    assert 1.0 <= composite <= 10.0


# ── verdict_for_score ──
@pytest.mark.parametrize("score,expected_verdict", [
    (9.0, "STRONG BUY"),
    (8.0, "STRONG BUY"),
    (7.5, "BUY"),
    (6.8, "BUY"),
    (6.0, "HOLD"),
    (5.2, "HOLD"),
    (4.5, "SELL"),
    (4.0, "SELL"),
    (3.0, "AVOID"),
    (1.0, "AVOID"),
])
def test_verdict_for_score(score, expected_verdict):
    verdict, css_class = verdict_for_score(score)
    assert verdict == expected_verdict
    assert css_class in ("strong-buy", "buy", "hold", "sell", "avoid")


# ── parse_score ──
def test_parse_score():
    assert parse_score("SCORE: 7.5/10") == 7.5
    assert parse_score("score: 3/10\nSome text") == 3.0
    assert parse_score("SCORE: 9.2/10\nFundamentals are strong") == 9.2
    assert parse_score("No score here") is None
    assert parse_score("") is None
    assert parse_score("SCORE: 15/10") == 10.0  # clamped


# ── _normalize_query ──
def test_normalize_query():
    # _normalize_query strips exchange suffixes and non-alphanumeric chars
    assert _normalize_query("SBIN.NS") == "SBIN"
    assert _normalize_query("SBI NSE") == "SBINSE"
    assert _normalize_query("State Bank of India") == "STATEBANKOFINDIA"
    assert _normalize_query("") == ""


# ── resolve_ticker ──
def test_resolve_ticker_known():
    result = resolve_ticker("SBIN")
    assert result["symbol"] == "SBIN.NS"
    assert result["source"] in ("direct", "map")


def test_resolve_ticker_alias():
    result = resolve_ticker("HDFC Bank")
    assert result["symbol"] == "HDFCBANK.NS"
    # Source can be "direct" (if yfinance validates it) or "map" (from KNOWN_TICKERS)
    assert result["source"] in ("direct", "map", "search")


def test_resolve_ticker_empty():
    result = resolve_ticker("")
    assert result["symbol"] == ""
    assert result["source"] == "unknown"


def test_search_yfinance_converts_bse_result_to_nse(monkeypatch):
    def fake_search_quotes(query):
        return [
            {
                "symbol": "TATASTEEL.BO",
                "exchange": "BSE",
                "shortname": "Tata Steel Limited",
            }
        ]

    monkeypatch.setattr(logic, "search_quotes", fake_search_quotes)

    result = _search_yfinance("Tata Steel")

    assert result["symbol"] == "TATASTEEL.NS"
    assert result["source"] == "search"
    assert result["name"] == "Tata Steel Limited"


def test_validate_ticker_returns_false_on_rate_limit(monkeypatch):
    def fake_ticker_history(symbol, period="5d"):
        raise YFinanceRateLimitError("Yahoo Finance rate limit exceeded")

    monkeypatch.setattr(logic, "yf", object())
    monkeypatch.setattr(logic, "ticker_history", fake_ticker_history)

    assert _validate_ticker("TATASTEEL.NS") is False


@pytest.mark.parametrize("inp,expected", [
    ("Tata Steel", "TATASTEEL.NS"),
    ("HDFC Life", "HDFCLIFE.NS"),
    ("National Aluminium", "NATIONALUM.NS"),
    ("Supriya Life Science", "SUPRIYA.NS"),
    ("Advait", "ADVAIT.NS"),
    ("Avantifeeds", "AVANTIFEED.NS"),
    ("Avanti Feeds", "AVANTIFEED.NS"),
    ("Eicher Motors", "EICHERMOT.NS"),
    ("Bajaj Finance and Insurance", "BAJAJFINSV.NS"),
    ("Divis Laboratories", "DIVISLAB.NS"),
    ("Pidilite Industries", "PIDILITIND.NS"),
    ("Power Finance", "PFC.NS"),
    ("Indian Oil", "IOC.NS"),
    ("Dr Lal Pathlabs", "LALPATHLAB.NS"),
    ("Metropolis Healthcare", "METROPOLIS.NS"),
])
def test_resolve_ticker_new_known_tickers(monkeypatch, inp, expected):
    monkeypatch.setattr(logic, "_validate_ticker", lambda symbol: False)
    monkeypatch.setattr(
        logic,
        "_search_yfinance",
        lambda query: {"symbol": "", "name": "", "source": "unknown"},
    )

    result = resolve_ticker(inp)

    assert result["symbol"] == expected
    assert result["source"] == "map"


@pytest.mark.parametrize("inp,expected", [
    ("M&M", "M&M.NS"),
    ("MCDOWELL-N", "MCDOWELL-N.NS"),
    ("M&MFIN", "M&MFIN.NS"),
    ("BAJAJ-AUTO", "BAJAJ-AUTO.NS"),
    ("BAJAJ AUTO", "BAJAJ-AUTO.NS"),
    ("BAJAJAUTO", "BAJAJ-AUTO.NS"),
])
def test_resolve_ticker_special_tickers(monkeypatch, inp, expected):
    monkeypatch.setattr(logic, "_validate_ticker", lambda symbol: False)

    result = resolve_ticker(inp)

    assert result["symbol"] == expected
    assert result["source"] == "special"


def test_search_yfinance_skips_numeric_bse(monkeypatch):
    """Numeric BSE symbols (e.g. 500112.BO) must NOT be converted to .NS."""
    def fake_search_quotes(query):
        return [
            {
                "symbol": "500112.BO",
                "exchange": "BSE",
                "shortname": "Some BSE only stock",
            },
            {
                "symbol": "TATASTEEL.BO",
                "exchange": "BSE",
                "shortname": "Tata Steel Limited",
            },
        ]

    monkeypatch.setattr(logic, "search_quotes", fake_search_quotes)

    result = _search_yfinance("test")

    # Should pick TATASTEEL.BO (alphabetic) and convert, skip 500112.BO (numeric)
    assert result["symbol"] == "TATASTEEL.NS"
    assert result["source"] == "search"


def test_resolve_ticker_garbage_returns_unknown(monkeypatch):
    """Garbage input must return empty symbol, not a bogus .NS fallback."""
    monkeypatch.setattr(
        logic,
        "resolve_from_symbol_master",
        lambda text: {"symbol": "", "name": "", "source": "unknown"},
    )
    monkeypatch.setattr(logic, "_validate_ticker", lambda symbol: False)
    monkeypatch.setattr(
        logic,
        "_search_yfinance",
        lambda query: {"symbol": "", "name": "", "source": "unknown"},
    )

    result = resolve_ticker("zzzxyznonexistent123")

    assert result["symbol"] == ""
    assert result["source"] == "unknown"


@pytest.mark.skip(reason="requires yfinance API — may be rate limited in CI")
def test_resolve_ticker_garbage():
    result = resolve_ticker("zzzxyznonexistent123")
    assert result["source"] in ("unknown", "search")
