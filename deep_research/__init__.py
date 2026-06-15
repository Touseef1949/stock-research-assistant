"""Deep Research package for the Stock Research Assistant.

The public entry point is `run_deep_research`, which orchestrates Screener,
yfinance, computed risk/valuation models, Plotly trend output, and an optional
DeepSeek thesis generator.
"""

from __future__ import annotations

from typing import Any, Callable

from .analyst_targets import fetch_analyst_targets
from .financial_trends import build_financial_trends
from .governance import evaluate_governance
from .peer_analysis import build_peer_comparison
from .risk_flags import evaluate_risk_flags
from .screener_client import fetch_screener_financials
from .thesis_agent import generate_investment_thesis
from .valuation import build_valuation_model

try:
    import streamlit as st
except Exception:  # pragma: no cover - supports import outside Streamlit tests
    st = None  # type: ignore[assignment]


def _cache_data(ttl: int) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Use Streamlit cache when available; otherwise behave like identity."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        if st is not None and hasattr(st, "cache_data"):
            return st.cache_data(ttl=ttl, show_spinner=False)(func)
        return func
    return decorator


def _normalize_peer_tickers(peer_tickers: list[str] | str | None) -> list[str]:
    if peer_tickers is None:
        return []
    if isinstance(peer_tickers, str):
        raw = peer_tickers.split(",")
    else:
        raw = [str(item) for item in peer_tickers]
    normalized: list[str] = []
    for item in raw:
        ticker = item.strip().upper()
        if not ticker:
            continue
        if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
            ticker = f"{ticker}.NS"
        if ticker not in normalized:
            normalized.append(ticker)
    return normalized


def _merge_warnings(*results: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for result in results:
        for warning in result.get("warnings", []) if isinstance(result, dict) else []:
            if warning and warning not in warnings:
                warnings.append(str(warning))
    return warnings


@_cache_data(ttl=3600)
def run_deep_research(
    symbol: str,
    market_data: dict[str, Any],
    api_key: str | None = None,
    peer_tickers: list[str] | str | None = None,
) -> dict[str, Any]:
    """Run the full Deep Research pipeline.

    Parameters
    ----------
    symbol:
        NSE ticker with or without `.NS`.
    market_data:
        Existing app market-data dictionary returned by `load_market_data`.
    api_key:
        DeepSeek API key. If missing, thesis generation falls back gracefully.
    peer_tickers:
        Optional comma-separated string or list of peers.
    """
    warnings: list[str] = []
    clean_symbol = (symbol or "").strip().upper()
    if not clean_symbol:
        return {"success": False, "symbol": symbol, "sections": {}, "warnings": ["Empty symbol supplied"]}
    if not clean_symbol.endswith(".NS") and not clean_symbol.endswith(".BO"):
        clean_symbol = f"{clean_symbol}.NS"

    peers = _normalize_peer_tickers(peer_tickers)

    screener = fetch_screener_financials(clean_symbol)
    if not screener.get("success"):
        warnings.extend(screener.get("warnings", []))

    peer_comparison = build_peer_comparison(clean_symbol, peers, market_data or {}, screener)
    analyst_targets = fetch_analyst_targets(clean_symbol)
    financial_trends = build_financial_trends(screener, market_data or {})
    risk_flags = evaluate_risk_flags(screener, market_data or {}, peer_comparison)
    valuation = build_valuation_model(market_data or {}, peer_comparison, screener)
    governance = evaluate_governance(screener)
    thesis = generate_investment_thesis(
        clean_symbol,
        market_data or {},
        peer_comparison,
        financial_trends,
        risk_flags,
        valuation,
        governance,
        api_key=api_key,
    )

    warnings.extend(_merge_warnings(
        screener,
        peer_comparison,
        analyst_targets,
        financial_trends,
        risk_flags,
        valuation,
        governance,
        thesis,
    ))

    sections = {
        "financials": screener,
        "peer_comparison": peer_comparison,
        "analyst_targets": analyst_targets,
        "financial_trends": financial_trends,
        "risk_flags": risk_flags,
        "valuation": valuation,
        "governance": governance,
        "thesis": thesis,
    }

    return {
        "success": True,
        "symbol": clean_symbol,
        "peer_tickers": peers,
        "sections": sections,
        # Also expose direct top-level aliases to keep Streamlit rendering simple.
        **sections,
        "warnings": warnings,
    }


__all__ = [
    "run_deep_research",
    "fetch_screener_financials",
    "build_peer_comparison",
    "fetch_analyst_targets",
    "build_financial_trends",
    "evaluate_risk_flags",
    "build_valuation_model",
    "evaluate_governance",
    "generate_investment_thesis",
]
