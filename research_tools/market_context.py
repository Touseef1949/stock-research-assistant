"""Normalize the existing market-data payload into evidence-backed tool results."""

from __future__ import annotations

from typing import Any, Callable

from core.research_contracts import Evidence, ToolResult, utc_now_iso


FALLBACK_SOURCES = {"screener_fallback", "web_search_fallback"}


def _source(data: dict[str, Any]) -> str:
    return str(data.get("source") or "unknown")


def _symbol(data: dict[str, Any]) -> str:
    return str(data.get("symbol") or data.get("base_symbol") or "")


def _confidence(data: dict[str, Any], technical: bool = False) -> str:
    source = _source(data)
    if source == "web_search_fallback":
        return "low"
    if source == "screener_fallback":
        return "low" if technical else "medium"
    history = data.get("history")
    if technical and history is None:
        return "low"
    if technical:
        try:
            if len(history) < 60:
                return "low"
        except TypeError:
            return "low"
    return "high"


def _result(tool_name: str, data: dict[str, Any], values: dict[str, Any], *, technical: bool = False) -> ToolResult:
    source = _source(data)
    symbol = _symbol(data)
    confidence = _confidence(data, technical=technical)
    as_of = str(data.get("as_of") or utc_now_iso())
    warnings: list[str] = []
    if source in FALLBACK_SOURCES:
        warnings.append(f"{tool_name} used fallback source: {source}")
    if technical and confidence == "low":
        warnings.append("Technical conclusions are limited because reliable price history is insufficient.")
    evidence = [
        Evidence(
            evidence_id=f"{symbol or 'UNKNOWN'}-{tool_name}-{index:03d}",
            metric=metric,
            value=value,
            source=source,
            as_of=as_of,
            confidence=confidence,
            kind="market" if metric in {"price", "change", "change_pct", "market_cap"} else "calculated",
            warnings=tuple(warnings),
        )
        for index, (metric, value) in enumerate(values.items(), start=1)
        if value is not None
    ]
    return ToolResult(
        tool_name=tool_name,
        success=bool(symbol),
        symbol=symbol,
        source=source,
        data=values,
        evidence=evidence,
        confidence=confidence,
        is_fallback=source in FALLBACK_SOURCES,
        warnings=warnings,
        as_of=as_of,
    )


def get_market_snapshot(data: dict[str, Any]) -> ToolResult:
    fundamentals = data.get("fundamentals") or {}
    return _result(
        "get_market_snapshot",
        data,
        {
            "name": data.get("name"),
            "price": data.get("price"),
            "change": data.get("change"),
            "change_pct": data.get("change_pct"),
            "market_cap": fundamentals.get("market_cap"),
            "trailing_pe": fundamentals.get("trailing_pe"),
            "price_to_book": fundamentals.get("price_to_book"),
        },
    )


def get_fundamental_metrics(data: dict[str, Any]) -> ToolResult:
    f = data.get("fundamentals") or {}
    keys = (
        "market_cap", "trailing_pe", "forward_pe", "price_to_book", "roe",
        "revenue_growth", "profit_margins", "debt_to_equity", "dividend_yield", "beta",
    )
    return _result("get_fundamental_metrics", data, {key: f.get(key) for key in keys})


def get_technical_metrics(data: dict[str, Any]) -> ToolResult:
    t = data.get("technicals") or {}
    keys = (
        "trend", "rsi", "macd", "macd_signal", "ema20", "ema50", "support",
        "resistance", "return_1y_pct", "max_drawdown_pct", "volatility_60d_pct",
    )
    return _result("get_technical_metrics", data, {key: t.get(key) for key in keys}, technical=True)


def evaluate_risk_flags(data: dict[str, Any]) -> ToolResult:
    f = data.get("fundamentals") or {}
    t = data.get("technicals") or {}
    debt = f.get("debt_to_equity")
    drawdown = t.get("max_drawdown_pct")
    volatility = t.get("volatility_60d_pct")
    values = {
        "debt_to_equity": debt,
        "max_drawdown_pct": drawdown,
        "volatility_60d_pct": volatility,
        "high_leverage_flag": bool(debt is not None and debt > 2),
        "deep_drawdown_flag": bool(drawdown is not None and drawdown < -35),
        "high_volatility_flag": bool(volatility is not None and volatility > 45),
    }
    return _result("evaluate_risk_flags", data, values, technical=True)


def get_valuation_inputs(data: dict[str, Any]) -> ToolResult:
    f = data.get("fundamentals") or {}
    return _result(
        "get_valuation_inputs",
        data,
        {
            "price": data.get("price"),
            "trailing_pe": f.get("trailing_pe"),
            "forward_pe": f.get("forward_pe"),
            "price_to_book": f.get("price_to_book"),
            "revenue_growth": f.get("revenue_growth"),
            "roe": f.get("roe"),
        },
    )


TOOL_FUNCTIONS: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
    "get_market_snapshot": get_market_snapshot,
    "get_fundamental_metrics": get_fundamental_metrics,
    "get_technical_metrics": get_technical_metrics,
    "evaluate_risk_flags": evaluate_risk_flags,
    "get_valuation_inputs": get_valuation_inputs,
}
