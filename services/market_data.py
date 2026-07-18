"""Market data pipeline service.

Provides the Screener/web/yfinance fallback chain for loading market data,
extracted from app.py to allow testing without importing the Streamlit entrypoint.
"""

from __future__ import annotations

import json
import re
import http.cookiejar
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

import streamlit as st

from logic import display_symbol, safe_float, compute_rsi, compute_macd
from deep_research.screener_client import fetch_screener_financials
from yf_client import (
    YFinanceRateLimitError,
    ticker_history,
    ticker_info,
)

try:
    import yfinance as yf
except Exception:
    yf = None


def _market_data_from_screener(nse_symbol: str) -> dict[str, Any]:
    """Build a market_data dict from Screener.in when yfinance is rate-limited."""
    base = display_symbol(nse_symbol)
    screener = fetch_screener_financials(nse_symbol)
    if not screener.get("success"):
        return _market_data_from_web_search(
            nse_symbol,
            reason="; ".join(screener.get("warnings", [])),
        )

    d = screener.get("data", {})
    ratios = d.get("ratios", {})
    price = safe_float(ratios.get("current_price")) or 0.0
    if not price:
        # Last resort: try a simple web search extraction for current price
        price = _current_price_from_web_sources(base)

    name = base
    if not price:
        raise RuntimeError(
            f"Could not determine current price for {nse_symbol} from Screener or web search."
        )

    market_cap_cr = safe_float(ratios.get("market_cap"))
    market_cap = market_cap_cr * 10_000_000 if market_cap_cr else None
    stock_pe = safe_float(ratios.get("stock_pe"))
    book_value = safe_float(ratios.get("book_value"))
    price_to_book = (price / book_value) if book_value else None
    roe_pct = safe_float(ratios.get("roe_pct"))
    debt_to_equity = safe_float(ratios.get("debt_to_equity"))
    dividend_yield = safe_float(ratios.get("dividend_yield"))
    if dividend_yield is not None and dividend_yield > 1:
        dividend_yield = dividend_yield / 100

    growth = d.get("growth", {})
    revenue_growth = safe_float(growth.get("sales_growth_3yr_pct"))
    if revenue_growth is not None:
        revenue_growth = revenue_growth / 100

    fundamentals = {
        "market_cap": market_cap,
        "trailing_pe": stock_pe,
        "forward_pe": None,
        "price_to_book": price_to_book,
        "roe": roe_pct / 100 if roe_pct is not None else None,
        "debt_to_equity": debt_to_equity,
        "revenue_growth": revenue_growth,
        "dividend_yield": dividend_yield,
        "profit_margins": None,
        "beta": None,
    }
    return _build_minimal_market_data(
        nse_symbol=nse_symbol,
        price=price,
        source="screener_fallback",
        name=name,
        fundamentals=fundamentals,
        screener_data=screener,
    )


def _safe_ratio_name(name: str) -> str:
    """Return a display name for the data source."""
    return str(name or "Unknown")


def _market_data_source_badge(data: dict[str, Any]) -> str:
    if data.get("source") == "kite_live":
        return "⚡ Live market data from Zerodha Kite"
    if data.get("source") == "screener_fallback":
        return "📡 Live market data from Screener.in (Yahoo Finance was temporarily unavailable)"
    if data.get("source") == "web_search_fallback":
        return "🌐 Price from public web fallback (Yahoo Finance and Screener.in were unavailable)"
    return "📈 Market data from Yahoo Finance"


def _synthetic_history(price: float) -> Any:
    """Create a minimal single-row history DataFrame as a safe placeholder."""
    try:
        import pandas as pd
    except Exception:
        return None
    today = pd.Timestamp.now().normalize()
    df = pd.DataFrame(
        {
            "Open": [price],
            "High": [price],
            "Low": [price],
            "Close": [price],
            "Volume": [0],
            "Adj Close": [price],
        },
        index=pd.DatetimeIndex([today], name="Date"),
    )
    df["EMA20"] = price
    df["EMA50"] = price
    df["RSI14"] = 50.0
    df["MACD"] = 0.0
    df["MACDSignal"] = 0.0
    return df


def _build_minimal_market_data(
    nse_symbol: str,
    price: float,
    source: str,
    name: str | None = None,
    fundamentals: dict[str, Any] | None = None,
    screener_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build safe market_data when only a current price is available."""
    base = display_symbol(nse_symbol)
    hist = _synthetic_history(price)
    fundamentals = fundamentals or {
        "market_cap": None,
        "trailing_pe": None,
        "forward_pe": None,
        "price_to_book": None,
        "roe": None,
        "debt_to_equity": None,
        "revenue_growth": None,
        "dividend_yield": None,
        "profit_margins": None,
        "beta": None,
    }
    technicals = {
        "trend": "Neutral",
        "rsi": 50.0,
        "macd": 0.0,
        "macd_signal": 0.0,
        "ema20": price,
        "ema50": price,
        "support": price * 0.95,
        "resistance": price * 1.05,
        "avg_volume_20d": 0.0,
        "latest_volume": 0.0,
        "max_drawdown_pct": -5.0,
        "return_1y_pct": 0.0,
        "volatility_60d_pct": 15.0,
    }
    data = {
        "symbol": nse_symbol,
        "base_symbol": base,
        "name": name or base,
        "exchange": "NSE",
        "currency": "INR",
        "price": price,
        "change": 0.0,
        "change_pct": 0.0,
        "history": hist,
        "info": {},
        "fundamentals": fundamentals,
        "technicals": technicals,
        "as_of": datetime.now().strftime("%d %b %Y, %H:%M"),
        "source": source,
    }
    if screener_data is not None:
        data["screener_data"] = screener_data
    return data


def _market_data_from_web_search(nse_symbol: str, reason: str = "") -> dict[str, Any]:
    """Build minimal market data from public web-derived current price sources."""
    price = _current_price_from_web_sources(display_symbol(nse_symbol))
    if price:
        return _build_minimal_market_data(
            nse_symbol=nse_symbol,
            price=price,
            source="web_search_fallback",
            name=display_symbol(nse_symbol),
        )

    details = f" Details: {reason}" if reason else ""
    raise RuntimeError(
        f"Yahoo Finance, Screener.in, and web fallback are unreachable for {nse_symbol}.{details}"
    )


def _web_get_text(url: str, headers: dict[str, str] | None = None, opener: Any = None) -> str:
    request = urllib.request.Request(
        url,
        headers=headers
        or {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    open_fn = opener.open if opener is not None else urllib.request.urlopen
    with open_fn(request, timeout=8) as response:
        return response.read().decode("utf-8", errors="ignore")


def _price_from_google_finance(symbol: str) -> float | None:
    url = f"https://www.google.com/finance/quote/{urllib.parse.quote(symbol)}:NSE"
    try:
        html = _web_get_text(url)
    except Exception:
        return None

    # Scope extraction to Google Finance's main quote header. Avoid generic
    # rupee/number matches because related-stock cards and index widgets on the
    # same page can contain unrelated prices.
    main_quote_pattern = (
        r'<div class="gO24Ff">[^<]+</div>\s*</div>\s*'
        r'<div class="LhDNu">.*?jsname="Pdsbrc"[^>]*>\s*'
        r"<span>\s*(?:₹|Rs\.?)?\s*([0-9,]+(?:\.[0-9]+)?)\s*</span>"
    )
    match = re.search(main_quote_pattern, html, flags=re.S)
    if not match:
        return None

    price = safe_float(match.group(1).replace(",", ""))
    if price and 10 < price < 50000:
        return price
    return None


def _price_from_nse_quote_api(symbol: str) -> float | None:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/get-quotes/equity",
    }
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar))
    try:
        _web_get_text("https://www.nseindia.com", headers=headers, opener=opener)
        url = "https://www.nseindia.com/api/quote-equity?symbol=" + urllib.parse.quote(symbol)
        payload = json.loads(_web_get_text(url, headers=headers, opener=opener))
    except Exception:
        return None

    price_info = payload.get("priceInfo", {}) if isinstance(payload, dict) else {}
    for key in ("lastPrice", "close", "previousClose"):
        price = safe_float(price_info.get(key))
        if price and 10 < price < 50000:
            return price
    return None


def _price_from_ddgs_snippets(symbol: str) -> float | None:
    """Try to extract a current price from web search snippets."""
    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(f"{symbol} NSE share price today", max_results=5))
        for result in results:
            body = str(result.get("body", ""))
            # Match patterns like 'Rs 1,021', '₹1,021', '1021.35'
            for match in re.finditer(r"(?:Rs\.?|₹)?\s*([0-9,]+(?:\.[0-9]+)?)", body):
                value = match.group(1).replace(",", "")
                try:
                    num = float(value)
                    if 10 < num < 50000:
                        return num
                except ValueError:
                    continue
    except Exception:
        pass
    return None


def _current_price_from_web_sources(symbol: str) -> float | None:
    """Try structured public web sources for a current price.

    We intentionally do NOT parse generic search snippets for price because
    snippets frequently contain unrelated values (percent changes, rankings,
    target prices) that look like valid prices.
    """
    base = display_symbol(symbol)
    for source in (
        _price_from_google_finance,
        _price_from_nse_quote_api,
    ):
        price = source(base)
        if price:
            return price
    return None


def _current_price_from_web_search(symbol: str) -> float | None:
    """Backward-compatible wrapper for the older helper name."""
    return _current_price_from_web_sources(symbol)


@st.cache_data(ttl=300, show_spinner=False)
def load_market_data(nse_symbol: str) -> dict[str, Any]:
    if yf is None:
        # yfinance not installed — try Screener/web fallback directly.
        return _market_data_from_screener(nse_symbol)

    try:
        info = ticker_info(nse_symbol)
        hist = ticker_history(nse_symbol, period="1y", interval="1d", auto_adjust=False)
        if hist is None or hist.empty:
            raise RuntimeError(f"No market data found for {nse_symbol}.")
    except YFinanceRateLimitError:
        return _market_data_from_screener(nse_symbol)

    hist = hist.dropna(subset=["Close"]).copy()
    close = hist["Close"]
    last_price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) > 1 else last_price
    change = last_price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0.0

    hist["EMA20"] = close.ewm(span=20, adjust=False).mean()
    hist["EMA50"] = close.ewm(span=50, adjust=False).mean()
    hist["RSI14"] = compute_rsi(close)
    hist["MACD"], hist["MACDSignal"] = compute_macd(close)

    latest = hist.iloc[-1]
    max_drawdown_pct = float(((close / close.cummax()) - 1).min() * 100)

    fundamentals = {
        "market_cap": info.get("marketCap"),
        "trailing_pe": info.get("trailingPE"),
        "forward_pe": info.get("forwardPE"),
        "price_to_book": info.get("priceToBook"),
        "roe": info.get("returnOnEquity"),
        "debt_to_equity": info.get("debtToEquity"),
        "revenue_growth": info.get("revenueGrowth"),
        "dividend_yield": info.get("dividendYield"),
        "profit_margins": info.get("profitMargins"),
        "beta": info.get("beta"),
    }
    technicals = {
        "trend": "Bullish"
        if latest["EMA20"] > latest["EMA50"]
        else "Bearish"
        if latest["EMA20"] < latest["EMA50"]
        else "Neutral",
        "rsi": safe_float(latest["RSI14"]),
        "macd": safe_float(latest["MACD"]),
        "macd_signal": safe_float(latest["MACDSignal"]),
        "ema20": safe_float(latest["EMA20"]),
        "ema50": safe_float(latest["EMA50"]),
        "support": float(close.tail(60).min()),
        "resistance": float(close.tail(60).max()),
        "avg_volume_20d": float(hist["Volume"].tail(20).mean()),
        "latest_volume": float(latest["Volume"]),
        "max_drawdown_pct": max_drawdown_pct,
        "return_1y_pct": (last_price / float(close.iloc[0]) - 1) * 100,
        "volatility_60d_pct": float(close.pct_change().tail(60).std() * (252**0.5) * 100),
    }

    data = {
        "symbol": nse_symbol,
        "base_symbol": display_symbol(nse_symbol),
        "name": info.get("longName") or info.get("shortName") or nse_symbol,
        "exchange": info.get("exchange", "NSE"),
        "currency": info.get("currency", "INR"),
        "price": last_price,
        "change": change,
        "change_pct": change_pct,
        "history": hist,
        "info": info,
        "fundamentals": fundamentals,
        "technicals": technicals,
        "as_of": datetime.now().strftime("%d %b %Y, %H:%M"),
        "source": "yfinance",
    }

    # Kite live-price overlay (optional — gracefully degrades)
    _try_kite_overlay(data, nse_symbol)

    return data


def _try_kite_overlay(data: dict, nse_symbol: str) -> None:
    """Overlay live Kite prices on top of yfinance/Screener data when available."""
    try:
        from services.kite_client import get_live_quote

        base = __import__("logic").display_symbol(nse_symbol)
        quote = get_live_quote(base)
        if not quote:
            return

        ltp = quote.get("ltp")
        if not ltp:
            return

        data["price"] = ltp
        data["change"] = quote.get("change", data.get("change", 0.0))
        data["change_pct"] = quote.get("change_pct", data.get("change_pct", 0.0))
        data["source"] = "kite_live"

        t = data.get("technicals", {})
        if quote.get("open"):
            t["open"] = quote["open"]
        if quote.get("high"):
            t["day_high"] = quote["high"]
        if quote.get("low"):
            t["day_low"] = quote["low"]
        if quote.get("volume"):
            t["latest_volume"] = quote["volume"]
    except Exception:
        pass  # Kite is optional — never crash on it
