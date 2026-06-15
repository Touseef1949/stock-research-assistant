"""Valuation model helpers for Deep Research."""

from __future__ import annotations

from typing import Any


def _unwrap(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return data.get("data") if isinstance(data.get("data"), dict) else data


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except Exception:
        return None


def _get(data: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict):
            return default
        cursor = cursor.get(key)
    return cursor if cursor is not None else default


def _series(data: dict[str, Any], path: list[str]) -> list[float]:
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict):
            return []
        cursor = cursor.get(key)
    if not isinstance(cursor, list):
        return []
    out: list[float] = []
    for item in cursor:
        parsed = _safe_float(item)
        if parsed is not None:
            out.append(parsed)
    return out


def _market_info(market_data: dict[str, Any]) -> dict[str, Any]:
    return market_data.get("fundamentals") or market_data.get("info") or market_data.get("ticker_info") or market_data


def _current_price(market_data: dict[str, Any], financials: dict[str, Any]) -> float | None:
    info = _market_info(market_data)
    for value in (
        market_data.get("price"),
        market_data.get("current_price"),
        info.get("currentPrice"),
        info.get("regularMarketPrice"),
        _get(financials, ["ratios", "current_price"]),
    ):
        parsed = _safe_float(value)
        if parsed not in (None, 0):
            return parsed
    return None


def _shares_outstanding(market_data: dict[str, Any], price: float | None) -> float | None:
    info = _market_info(market_data)
    shares = _safe_float(info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"))
    if shares:
        return shares
    market_cap = _safe_float(info.get("marketCap") or market_data.get("market_cap"))
    if market_cap and price:
        return market_cap / price
    return None


def _dcf_value_per_share(
    fcf: float,
    shares: float,
    growth: float,
    wacc: float,
    terminal_growth: float,
    years: int = 5,
) -> float | None:
    if fcf <= 0 or shares <= 0 or wacc <= terminal_growth:
        return None
    projected = []
    current = fcf
    for year in range(1, years + 1):
        current *= 1 + growth
        projected.append(current / ((1 + wacc) ** year))
    terminal_fcf = current * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    discounted_terminal = terminal_value / ((1 + wacc) ** years)
    equity_value = sum(projected) + discounted_terminal
    return equity_value / shares


def build_valuation_model(
    market_data: dict[str, Any] | None,
    peer_data: dict[str, Any] | None,
    financials: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a blended valuation model using multiples + DCF-lite."""
    warnings: list[str] = []
    market = market_data or {}
    peer = _unwrap(peer_data)
    fin = _unwrap(financials)
    info = _market_info(market)

    price = _current_price(market, fin)
    shares = _shares_outstanding(market, price)
    eps_series = _series(fin, ["profit_loss", "eps"])
    eps = eps_series[-1] if eps_series else _safe_float(info.get("trailingEps") or info.get("forwardEps"))
    revenue = _safe_float(info.get("totalRevenue"))
    ebitda_margin = _safe_float(info.get("ebitdaMargins"))
    if ebitda_margin is not None and ebitda_margin <= 1:
        ebitda_margin *= 100

    sales_growth = _safe_float(_get(fin, ["growth", "sales_growth_3yr_pct"]))
    profit_growth = _safe_float(_get(fin, ["growth", "profit_growth_3yr_pct"]))
    growth_pct = profit_growth if profit_growth is not None else sales_growth if sales_growth is not None else 8.0
    normalized_growth = max(min(growth_pct, 25.0), 2.0) / 100

    peer_stats = peer.get("peer_stats") if isinstance(peer.get("peer_stats"), dict) else {}
    peer_pe = _safe_float(_get(peer_stats, ["P/E", "median"])) or _safe_float(info.get("trailingPE"))
    peer_ev_ebitda = _safe_float(_get(peer_stats, ["EV/EBITDA", "median"])) or _safe_float(info.get("enterpriseToEbitda"))

    methods: list[dict[str, Any]] = []

    if eps not in (None, 0) and peer_pe not in (None, 0):
        fair_pe = eps * peer_pe
        methods.append({
            "method": "P/E peer median",
            "fair_value": fair_pe,
            "weight": 0.30,
            "assumption": f"EPS {eps:.2f} × peer median P/E {peer_pe:.2f}",
        })
    else:
        warnings.append("P/E fair value unavailable due to missing EPS or peer P/E")

    if revenue not in (None, 0) and ebitda_margin not in (None, 0) and shares not in (None, 0) and peer_ev_ebitda not in (None, 0):
        ebitda = revenue * (ebitda_margin / 100)
        fair_ev_ebitda = (ebitda * peer_ev_ebitda) / shares
        methods.append({
            "method": "EV/EBITDA peer median",
            "fair_value": fair_ev_ebitda,
            "weight": 0.20,
            "assumption": f"EBITDA margin {ebitda_margin:.1f}% × peer median EV/EBITDA {peer_ev_ebitda:.2f}",
        })
    else:
        warnings.append("EV/EBITDA fair value unavailable due to missing revenue, margin, shares, or peer multiple")

    if eps not in (None, 0):
        fair_peg_pe = max(min(growth_pct, 30), 8)  # PEG ≈ 1, with conservative bounds.
        methods.append({
            "method": "PEG-based fair value",
            "fair_value": eps * fair_peg_pe,
            "weight": 0.20,
            "assumption": f"PEG≈1 with fair P/E capped to {fair_peg_pe:.1f} based on growth {growth_pct:.1f}%",
        })
    else:
        warnings.append("PEG fair value unavailable due to missing EPS")

    fcf_series = _series(fin, ["cash_flow", "free_cash_flow"])
    latest_fcf_crore = fcf_series[-1] if fcf_series else None
    latest_fcf = None
    if latest_fcf_crore is not None:
        # Screener values are usually in ₹ crore. Convert crore to rupees for yfinance share count.
        latest_fcf = latest_fcf_crore * 10_000_000
    else:
        latest_fcf = _safe_float(info.get("freeCashflow") or info.get("operatingCashflow"))

    wacc = 0.12
    terminal_growth = 0.04
    dcf = None
    if latest_fcf not in (None, 0) and shares not in (None, 0):
        dcf = _dcf_value_per_share(abs(latest_fcf), shares, normalized_growth, wacc, terminal_growth)
        if dcf is not None:
            methods.append({
                "method": "DCF-lite",
                "fair_value": dcf,
                "weight": 0.30,
                "assumption": f"5-year FCF growth {normalized_growth * 100:.1f}%, WACC {wacc * 100:.1f}%, terminal growth {terminal_growth * 100:.1f}%",
            })
    if dcf is None:
        warnings.append("DCF-lite unavailable due to missing positive FCF or share count")

    weighted_values = [method for method in methods if _safe_float(method.get("fair_value")) is not None and _safe_float(method.get("weight"))]
    if weighted_values:
        total_weight = sum(float(method["weight"]) for method in weighted_values)
        base = sum(float(method["fair_value"]) * float(method["weight"]) for method in weighted_values) / total_weight
        low = min(float(method["fair_value"]) for method in weighted_values) * 0.90
        high = max(float(method["fair_value"]) for method in weighted_values) * 1.10
    else:
        base = low = high = None

    upside_pct = None
    if price not in (None, 0) and base is not None:
        upside_pct = ((base - price) / price) * 100

    sensitivity_table: list[list[Any]] = []
    if latest_fcf not in (None, 0) and shares not in (None, 0):
        growth_rates = [0.06, 0.08, 0.10, 0.12, 0.15]
        wacc_rates = [0.10, 0.11, 0.12, 0.13, 0.14]
        sensitivity_table.append(["Growth/WACC", *[f"{rate * 100:.0f}%" for rate in wacc_rates]])
        for growth_rate in growth_rates:
            row = [f"{growth_rate * 100:.0f}%"]
            for wacc_rate in wacc_rates:
                value = _dcf_value_per_share(abs(latest_fcf), shares, growth_rate, wacc_rate, terminal_growth)
                row.append(round(value, 2) if value is not None else None)
            sensitivity_table.append(row)

    return {
        "success": True,
        "source": "computed",
        "data": {
            "current_price": price,
            "fair_value_range": {
                "low": round(low, 2) if low is not None else None,
                "base": round(base, 2) if base is not None else None,
                "high": round(high, 2) if high is not None else None,
            },
            "upside_pct": round(upside_pct, 2) if upside_pct is not None else None,
            "methods": methods,
            "assumptions": {
                "growth_pct": round(normalized_growth * 100, 2),
                "wacc_pct": round(wacc * 100, 2),
                "terminal_growth_pct": round(terminal_growth * 100, 2),
                "shares_outstanding": shares,
                "latest_fcf": latest_fcf,
            },
            "sensitivity_table": sensitivity_table,
        },
        "warnings": warnings,
    }
