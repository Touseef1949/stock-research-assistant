"""Pure business logic for Stock Research Assistant — zero Streamlit dependencies.

Extracted from app.py so pytest can test without Streamlit runtime.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd

from yf_client import search_quotes, ticker_history, ticker_info

try:
    import yfinance as yf
except Exception:
    yf = None

# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------

KNOWN_TICKER_NAMES = {
    "ADANIENT.NS": "Adani Enterprises Ltd",
    "ASIANPAINT.NS": "Asian Paints Ltd",
    "AXISBANK.NS": "Axis Bank Ltd",
    "BAJFINANCE.NS": "Bajaj Finance Ltd",
    "BHARTIARTL.NS": "Bharti Airtel Ltd",
    "COALINDIA.NS": "Coal India Ltd",
    "HCLTECH.NS": "HCL Technologies Ltd",
    "HDFCBANK.NS": "HDFC Bank Ltd",
    "HINDUNILVR.NS": "Hindustan Unilever Ltd",
    "ICICIBANK.NS": "ICICI Bank Ltd",
    "INFY.NS": "Infosys Ltd",
    "ITC.NS": "ITC Ltd",
    "KOTAKBANK.NS": "Kotak Mahindra Bank Ltd",
    "LT.NS": "Larsen & Toubro Ltd",
    "MARUTI.NS": "Maruti Suzuki India Ltd",
    "NESTLEIND.NS": "Nestle India Ltd",
    "NTPC.NS": "NTPC Ltd",
    "ONGC.NS": "Oil and Natural Gas Corporation Ltd",
    "POWERGRID.NS": "Power Grid Corporation of India Ltd",
    "RELIANCE.NS": "Reliance Industries Ltd",
    "SBIN.NS": "State Bank of India",
    "SUNPHARMA.NS": "Sun Pharmaceutical Industries Ltd",
    "TATAMOTORS.NS": "Tata Motors Ltd",
    "TCS.NS": "Tata Consultancy Services Ltd",
    "TITAN.NS": "Titan Company Ltd",
    "ULTRACEMCO.NS": "UltraTech Cement Ltd",
    "WIPRO.NS": "Wipro Ltd",
}


def _normalize_query(s: str) -> str:
    """Normalize free-text company/ticker input for resolver matching."""
    clean = re.sub(r"\.(NS|NSE|BSE|BO)$", "", str(s or "").upper().strip())
    return re.sub(r"[^A-Z0-9]", "", clean)


KNOWN_TICKERS = {
    # Existing quick picks.
    "SBIN": "SBIN.NS",
    "SBI": "SBIN.NS",
    "STATEBANKOFINDIA": "SBIN.NS",
    "RELIANCE": "RELIANCE.NS",
    "RELIANCEINDUSTRIES": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "TATACONSULTANCYSERVICES": "TCS.NS",
    # Common large-cap NSE names and aliases.
    "INFY": "INFY.NS",
    "INFOSYS": "INFY.NS",
    "INFOSYSLTD": "INFY.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "HDFCBANKLTD": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS",
    "ICICIBANKLTD": "ICICIBANK.NS",
    "ITC": "ITC.NS",
    "ITCLTD": "ITC.NS",
    "HINDUNILVR": "HINDUNILVR.NS",
    "HINDUSTANUNILEVER": "HINDUNILVR.NS",
    "HINDUSTANUNILEVERLTD": "HINDUNILVR.NS",
    "KOTAKBANK": "KOTAKBANK.NS",
    "KOTAKMAHINDRABANK": "KOTAKBANK.NS",
    "LT": "LT.NS",
    "LARSENTOUBRO": "LT.NS",
    "LARSENANDTOUBRO": "LT.NS",
    "ONGC": "ONGC.NS",
    "OILANDNATURALGASCORPORATION": "ONGC.NS",
    "AXISBANK": "AXISBANK.NS",
    "AXISBANKLTD": "AXISBANK.NS",
    "ADANIENT": "ADANIENT.NS",
    "ADANIENTERPRISES": "ADANIENT.NS",
    "TATAMOTORS": "TATAMOTORS.NS",
    "TATAMOTORSLTD": "TATAMOTORS.NS",
    "MARUTI": "MARUTI.NS",
    "MARUTISUZUKI": "MARUTI.NS",
    "SUNPHARMA": "SUNPHARMA.NS",
    "SUNPHARMACEUTICAL": "SUNPHARMA.NS",
    "SUNPHARMACEUTICALINDUSTRIES": "SUNPHARMA.NS",
    "WIPRO": "WIPRO.NS",
    "WIPROLTD": "WIPRO.NS",
    "HCLTECH": "HCLTECH.NS",
    "HCLTECHNOLOGIES": "HCLTECH.NS",
    "BHARTIARTL": "BHARTIARTL.NS",
    "BHARTIAIRTEL": "BHARTIARTL.NS",
    "BAJFINANCE": "BAJFINANCE.NS",
    "BAJAJFINANCE": "BAJFINANCE.NS",
    "ASIANPAINT": "ASIANPAINT.NS",
    "ASIANPAINTS": "ASIANPAINT.NS",
    "NESTLEIND": "NESTLEIND.NS",
    "NESTLEINDIA": "NESTLEIND.NS",
    "TITAN": "TITAN.NS",
    "TITANCOMPANY": "TITAN.NS",
    "ULTRACEMCO": "ULTRACEMCO.NS",
    "ULTRATECHCEMENT": "ULTRACEMCO.NS",
    "POWERGRID": "POWERGRID.NS",
    "POWERGRIDCORPORATION": "POWERGRID.NS",
    "NTPC": "NTPC.NS",
    "NTPCLTD": "NTPC.NS",
    "COALINDIA": "COALINDIA.NS",
    "COALINDIALTD": "COALINDIA.NS",
}


def _ticker_result(symbol: str, source: str, name: str = "") -> dict[str, str]:
    return {
        "symbol": symbol,
        "name": name or KNOWN_TICKER_NAMES.get(symbol, symbol.replace(".NS", "")),
        "source": source,
    }


def _validate_ticker(symbol: str) -> bool:
    if yf is None:
        return False
    try:
        history = ticker_history(symbol, period="5d")
        return history is not None and not history.empty
    except Exception:
        return False


def _search_yfinance(query: str) -> dict[str, str]:
    try:
        quotes = search_quotes(query)
    except Exception:
        return {"symbol": "", "name": "", "source": "unknown"}
    if not quotes:
        return {"symbol": "", "name": "", "source": "unknown"}

    def score(quote: dict[str, Any]) -> int:
        symbol = str(quote.get("symbol", "")).upper()
        exchange = str(quote.get("exchange", "")).upper()
        if symbol.endswith(".NS"):
            return 3
        if exchange in {"NSE", "NSI"}:
            return 2
        return 0

    for quote in sorted(quotes, key=score, reverse=True):
        symbol = str(quote.get("symbol", "")).upper().strip()
        if not symbol:
            continue
        exchange = str(quote.get("exchange", "")).upper()
        if symbol.endswith(".NS") or exchange in {"NSE", "NSI"}:
            if not symbol.endswith(".NS"):
                symbol = f"{_normalize_query(symbol)}.NS"
            name = str(quote.get("longname") or quote.get("shortname") or quote.get("name") or "")
            return _ticker_result(symbol, "search", name)
    return {"symbol": "", "name": "", "source": "unknown"}


def to_nse_symbol(symbol: str) -> str:
    """Normalize a ticker to the NSE yfinance format (e.g. SBIN → SBIN.NS)."""
    clean = re.sub(r"[^A-Za-z0-9.]", "", symbol or "").upper().strip(".")
    if not clean:
        return ""
    return clean if clean.endswith(".NS") else f"{clean}.NS"


def resolve_ticker(text: str) -> dict[str, str]:
    """Resolve a company name, alias, or ticker-like input to an NSE yfinance symbol."""
    normalized = _normalize_query(text)
    if not normalized:
        return {"symbol": "", "name": "", "source": "unknown"}

    if re.fullmatch(r"[A-Z0-9]{1,20}", normalized):
        candidate = f"{normalized}.NS"
        if _validate_ticker(candidate):
            return _ticker_result(candidate, "direct")

    mapped = KNOWN_TICKERS.get(normalized)
    if mapped:
        return _ticker_result(mapped, "map")

    return _search_yfinance(str(text or "").strip())


def display_symbol(nse_symbol: str) -> str:
    """Reverse of to_nse_symbol (e.g. SBIN.NS → SBIN)."""
    return nse_symbol.replace(".NS", "").upper()


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------


def clamp_score(value: float) -> float:
    """Clamp a score to [1.0, 10.0]."""
    return max(1.0, min(10.0, float(value)))


def safe_float(value: Any) -> Optional[float]:
    """Try to convert to float, returning None on NaN/missing."""
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def money(value: Any) -> str:
    """Format a number as INR with appropriate suffix (Cr, K Cr, T)."""
    value = safe_float(value)
    if value is None:
        return "Unavailable"
    if abs(value) >= 1e12:
        return f"₹{value / 1e12:.2f}T"
    if abs(value) >= 1e10:
        return f"₹{value / 1e10:.2f}K Cr"
    if abs(value) >= 1e7:
        return f"₹{value / 1e7:.2f}Cr"
    return f"₹{value:,.0f}"


def number(value: Any, suffix: str = "") -> str:
    """Format a number with 2 decimal places and optional suffix."""
    value = safe_float(value)
    if value is None:
        return "Unavailable"
    return f"{value:,.2f}{suffix}"


def pct(value: Any) -> str:
    """Format a decimal ratio as a percentage string."""
    value = safe_float(value)
    if value is None:
        return "Unavailable"
    return f"{value * 100:.2f}%"


# ---------------------------------------------------------------------------
# Technical indicators
# ---------------------------------------------------------------------------


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index."""
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def compute_macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Compute MACD and signal line."""
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    return macd, signal


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------


def local_scores(
    fundamentals: dict[str, Any],
    technicals: dict[str, Any],
) -> dict[str, float]:
    """Score stock on 4 dimensions using local rules (no LLM)."""
    # ── Fundamentals ──
    fund_score = 5.0
    pe = safe_float(fundamentals.get("trailing_pe"))
    if pe is not None:
        if 0 < pe <= 25:
            fund_score += 1.3
        elif pe <= 40:
            fund_score += 0.4
        elif pe > 60:
            fund_score -= 1.3
    roe = safe_float(fundamentals.get("roe"))
    if roe is not None:
        if roe >= 0.18:
            fund_score += 1.4
        elif roe >= 0.12:
            fund_score += 0.7
        elif roe < 0.06:
            fund_score -= 1.0
    debt = safe_float(fundamentals.get("debt_to_equity"))
    if debt is not None:
        if debt <= 60:
            fund_score += 0.8
        elif debt > 180:
            fund_score -= 1.2
    growth = safe_float(fundamentals.get("revenue_growth"))
    if growth is not None:
        fund_score += 0.8 if growth > 0.10 else -0.5 if growth < 0 else 0

    # ── Technicals ──
    tech_score = 5.0
    trend = technicals.get("trend")
    if trend == "Bullish":
        tech_score += 1.4
    elif trend == "Bearish":
        tech_score -= 1.4
    rsi = safe_float(technicals.get("rsi"))
    if rsi is not None:
        if 45 <= rsi <= 65:
            tech_score += 0.9
        elif 30 <= rsi < 45:
            tech_score += 0.2
        elif rsi > 75 or rsi < 25:
            tech_score -= 0.9
    macd = safe_float(technicals.get("macd"))
    signal = safe_float(technicals.get("macd_signal"))
    if macd is not None and signal is not None:
        tech_score += 0.7 if macd > signal else -0.4
    one_year = safe_float(technicals.get("return_1y_pct"))
    if one_year is not None:
        tech_score += 0.8 if one_year > 15 else -0.6 if one_year < -15 else 0

    # ── Risk ──
    risk_score = 7.0
    drawdown = abs(safe_float(technicals.get("max_drawdown_pct")) or 0)
    volatility = safe_float(technicals.get("volatility_60d_pct")) or 0
    beta = safe_float(fundamentals.get("beta"))
    if drawdown > 35:
        risk_score -= 2.0
    elif drawdown > 22:
        risk_score -= 1.0
    if volatility > 45:
        risk_score -= 1.2
    elif volatility > 32:
        risk_score -= 0.6
    if debt is not None and debt > 180:
        risk_score -= 0.8
    if beta is not None and beta > 1.4:
        risk_score -= 0.6

    # ── Sentiment ──
    sent_score = 5.0
    if one_year is not None:
        sent_score += 0.7 if one_year > 10 else -0.5 if one_year < -10 else 0
    if growth is not None:
        sent_score += 0.5 if growth > 0.08 else -0.4 if growth < 0 else 0

    return {
        "Fundamentals": clamp_score(fund_score),
        "Technicals": clamp_score(tech_score),
        "Sentiment": clamp_score(sent_score),
        "Risk": clamp_score(risk_score),
    }


# ---------------------------------------------------------------------------
# Verdict & composite
# ---------------------------------------------------------------------------

SCORE_ORDER = ["Fundamentals", "Technicals", "Sentiment", "Risk"]


def verdict_for_score(score: float) -> tuple[str, str]:
    """Map composite score to verdict + CSS class."""
    if score >= 8.0:
        return "STRONG BUY", "strong-buy"
    if score >= 6.8:
        return "BUY", "buy"
    if score >= 5.2:
        return "HOLD", "hold"
    if score >= 4.0:
        return "SELL", "sell"
    return "AVOID", "avoid"


def composite_score(scores: dict[str, float]) -> float:
    """Weighted composite of the 4 dimension scores."""
    weights = {"Fundamentals": 0.32, "Technicals": 0.26,
               "Sentiment": 0.18, "Risk": 0.24}
    total = sum(scores[name] * weights[name] for name in weights if name in scores)
    used = sum(weights[name] for name in weights if name in scores)
    return clamp_score(total / used) if used else 5.0


def parse_score(text: str) -> Optional[float]:
    """Extract 'SCORE: X.X/10' from agent output text."""
    match = re.search(
        r"SCORE\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*10",
        text or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return clamp_score(float(match.group(1)))
