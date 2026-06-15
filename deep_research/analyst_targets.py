"""Analyst target extraction from yfinance."""

from __future__ import annotations

from typing import Any

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None  # type: ignore[assignment]


def _ensure_ns(symbol: str) -> str:
    cleaned = (symbol or "").strip().upper()
    if not cleaned:
        return cleaned
    if cleaned.endswith(".NS") or cleaned.endswith(".BO"):
        return cleaned
    return f"{cleaned}.NS"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except Exception:
        return None


def _current_price(info: dict[str, Any]) -> float | None:
    for key in ("currentPrice", "regularMarketPrice", "previousClose", "open"):
        price = _safe_float(info.get(key))
        if price not in (None, 0):
            return price
    return None


def fetch_analyst_targets(symbol: str) -> dict[str, Any]:
    """Fetch analyst consensus and target-price data from yfinance."""
    warnings: list[str] = []
    ticker_symbol = _ensure_ns(symbol)
    if not ticker_symbol:
        return {"success": False, "source": "yfinance", "data": None, "warnings": ["Empty symbol supplied"]}
    if yf is None:
        return {"success": False, "source": "yfinance", "data": None, "warnings": ["yfinance is not available"]}

    try:
        info = yf.Ticker(ticker_symbol).info or {}
    except Exception as exc:
        return {
            "success": False,
            "source": "yfinance",
            "data": None,
            "warnings": [f"Could not fetch analyst targets for {ticker_symbol}: {exc}"],
        }

    price = _current_price(info)
    target_mean = _safe_float(info.get("targetMeanPrice"))
    target_high = _safe_float(info.get("targetHighPrice"))
    target_low = _safe_float(info.get("targetLowPrice"))
    opinions = int(_safe_float(info.get("numberOfAnalystOpinions")) or 0)

    upside_pct = None
    if price not in (None, 0) and target_mean not in (None, 0):
        upside_pct = ((target_mean - price) / price) * 100

    has_coverage = opinions > 0 and target_mean not in (None, 0)
    if not has_coverage:
        warnings.append("No usable analyst coverage found in yfinance. This is common for small-caps and less-covered NSE stocks.")

    return {
        "success": True,
        "source": "yfinance",
        "data": {
            "symbol": ticker_symbol,
            "current_price": price,
            "target_mean_price": target_mean,
            "target_high_price": target_high,
            "target_low_price": target_low,
            "number_of_analyst_opinions": opinions,
            "recommendation_key": info.get("recommendationKey") or "unavailable",
            "recommendation_mean": _safe_float(info.get("recommendationMean")),
            "upside_downside_pct": upside_pct,
            "has_coverage": has_coverage,
        },
        "warnings": warnings,
    }
