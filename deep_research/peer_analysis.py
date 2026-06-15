"""Peer-comparison helpers for the Deep Research tab."""

from __future__ import annotations

from typing import Any

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore[assignment]

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None  # type: ignore[assignment]


METRIC_COLUMNS = [
    "Market Cap",
    "Revenue",
    "Revenue Growth %",
    "P/E",
    "P/B",
    "EV/EBITDA",
    "ROE %",
    "ROCE %",
    "D/E",
    "NIM %",
    "OPM %",
    "NPM %",
    "Div Yield %",
]


FINANCIAL_KEYWORDS = ("bank", "financial", "finance", "nbfc", "insurance", "credit", "capital")


def _ensure_ns(symbol: str) -> str:
    cleaned = (symbol or "").strip().upper()
    if not cleaned:
        return cleaned
    if cleaned.endswith(".NS") or cleaned.endswith(".BO"):
        return cleaned
    return f"{cleaned}.NS"


def _base_symbol(symbol: str) -> str:
    cleaned = (symbol or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return cleaned


def _safe_float(value: Any, multiplier: float = 1.0) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value) * multiplier
    except Exception:
        return None


def _get_nested(data: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return default
        cursor = cursor[key]
    return cursor


def _market_data_info(market_data: dict[str, Any]) -> dict[str, Any]:
    return (
        market_data.get("fundamentals")
        or market_data.get("info")
        or market_data.get("ticker_info")
        or market_data.get("data", {}).get("fundamentals")
        or {}
    )


def _last_value(values: Any) -> float | None:
    if isinstance(values, list):
        for value in reversed(values):
            parsed = _safe_float(value)
            if parsed is not None:
                return parsed
        return None
    return _safe_float(values)


def _infer_financial_sector(symbol: str, info: dict[str, Any], screener_data: dict[str, Any] | None = None) -> bool:
    sector = str(info.get("sector") or info.get("industry") or "").lower()
    name = str(info.get("longName") or info.get("shortName") or symbol).lower()
    symbol_lower = symbol.lower()
    if any(keyword in sector or keyword in name or keyword in symbol_lower for keyword in FINANCIAL_KEYWORDS):
        return True
    # Screener ratios for banks often lack normal debt metrics; this is a soft hint only.
    if screener_data:
        de = _get_nested(screener_data, ["data", "ratios", "debt_to_equity"])
        roce = _get_nested(screener_data, ["data", "ratios", "roce_pct"])
        if de is None and roce is None and any(k in symbol_lower for k in ("bank", "fin")):
            return True
    return False


def _row_from_info(symbol: str, info: dict[str, Any], screener_data: dict[str, Any] | None = None) -> dict[str, Any]:
    is_financial = _infer_financial_sector(symbol, info, screener_data)
    row = {
        "Symbol": _ensure_ns(symbol),
        "Company": info.get("longName") or info.get("shortName") or _base_symbol(symbol),
        "Sector": info.get("sector") or "Unavailable",
        "Market Cap": _safe_float(info.get("marketCap")),
        "Revenue": _safe_float(info.get("totalRevenue")),
        "Revenue Growth %": _safe_float(info.get("revenueGrowth"), 100.0),
        "P/E": _safe_float(info.get("trailingPE") or info.get("forwardPE")),
        "P/B": _safe_float(info.get("priceToBook")),
        "EV/EBITDA": _safe_float(info.get("enterpriseToEbitda")),
        "ROE %": _safe_float(info.get("returnOnEquity"), 100.0),
        "ROCE %": _safe_float(info.get("returnOnCapital") or info.get("returnOnAssets"), 100.0),
        "D/E": None if is_financial else _safe_float(info.get("debtToEquity"), 0.01),
        "NIM %": _safe_float(info.get("netInterestMargin"), 100.0) if is_financial else None,
        "OPM %": _safe_float(info.get("operatingMargins"), 100.0),
        "NPM %": _safe_float(info.get("profitMargins"), 100.0),
        "Div Yield %": _safe_float(info.get("dividendYield"), 100.0),
        "Is Financial": is_financial,
    }

    if screener_data and _base_symbol(symbol) == _base_symbol(str(_get_nested(screener_data, ["data", "symbol"], symbol))):
        ratios = _get_nested(screener_data, ["data", "ratios"], {}) or {}
        growth = _get_nested(screener_data, ["data", "growth"], {}) or {}
        pl = _get_nested(screener_data, ["data", "profit_loss"], {}) or {}
        row["ROE %"] = row["ROE %"] if row["ROE %"] is not None else _safe_float(ratios.get("roe_pct"))
        row["ROCE %"] = row["ROCE %"] if row["ROCE %"] is not None else _safe_float(ratios.get("roce_pct"))
        if not is_financial:
            row["D/E"] = row["D/E"] if row["D/E"] is not None else _safe_float(ratios.get("debt_to_equity"))
        row["Revenue Growth %"] = row["Revenue Growth %"] if row["Revenue Growth %"] is not None else _safe_float(growth.get("sales_growth_3yr_pct"))
        row["OPM %"] = row["OPM %"] if row["OPM %"] is not None else _last_value(pl.get("opm_pct"))
        row["NPM %"] = row["NPM %"] if row["NPM %"] is not None else _last_value(pl.get("npm_pct"))
    return row


def _fetch_yfinance_info(symbol: str) -> tuple[dict[str, Any], str | None]:
    if yf is None:
        return {}, "yfinance is not available"
    ticker_symbol = _ensure_ns(symbol)
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info or {}
        if not info:
            return {}, f"No yfinance info returned for {ticker_symbol}"
        return info, None
    except Exception as exc:
        return {}, f"Could not fetch yfinance info for {ticker_symbol}: {exc}"


def _stats(rows: list[dict[str, Any]], columns: list[str]) -> dict[str, dict[str, float | None]]:
    stats: dict[str, dict[str, float | None]] = {}
    if pd is None:
        return {col: {"median": None, "p25": None, "p75": None} for col in columns}
    if not rows:
        return {col: {"median": None, "p25": None, "p75": None} for col in columns}
    frame = pd.DataFrame(rows)
    for col in columns:
        if col not in frame:
            stats[col] = {"median": None, "p25": None, "p75": None}
            continue
        series = pd.to_numeric(frame[col], errors="coerce").dropna()
        if series.empty:
            stats[col] = {"median": None, "p25": None, "p75": None}
        else:
            stats[col] = {
                "median": float(series.median()),
                "p25": float(series.quantile(0.25)),
                "p75": float(series.quantile(0.75)),
            }
    return stats


def _premium_discount_flags(target: dict[str, Any], peer_stats: dict[str, dict[str, float | None]]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for metric in ("P/E", "P/B", "EV/EBITDA"):
        target_value = _safe_float(target.get(metric))
        median = peer_stats.get(metric, {}).get("median")
        if target_value is None or median in (None, 0):
            continue
        diff_pct = ((target_value - median) / median) * 100
        flags.append({
            "metric": metric,
            "target": target_value,
            "peer_median": median,
            "premium_discount_pct": diff_pct,
            "label": "premium" if diff_pct > 5 else "discount" if diff_pct < -5 else "in line",
            "explanation": f"Target trades at {abs(diff_pct):.1f}% {'premium' if diff_pct > 0 else 'discount'} to peer median on {metric}.",
        })
    return flags


def _size_warnings(target: dict[str, Any], peers: list[dict[str, Any]]) -> list[str]:
    warnings: list[str] = []
    target_cap = _safe_float(target.get("Market Cap"))
    if target_cap in (None, 0):
        return warnings
    for peer in peers:
        peer_cap = _safe_float(peer.get("Market Cap"))
        if peer_cap in (None, 0):
            continue
        ratio = peer_cap / target_cap
        if ratio >= 10:
            warnings.append(f"{peer.get('Symbol')} is more than 10x larger by market cap; valuation comparison may be distorted")
        elif ratio <= 0.10:
            warnings.append(f"{peer.get('Symbol')} is less than one-tenth of target market cap; size mismatch may be material")
    return warnings


def build_peer_comparison(
    symbol: str,
    peer_tickers: list[str] | str | None,
    market_data: dict[str, Any],
    screener_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build a target-vs-peer fundamental comparison table using yfinance.

    The function never raises for missing peer data; failed tickers are skipped
    and reported in warnings.
    """
    warnings: list[str] = []
    if isinstance(peer_tickers, str):
        peers = [item.strip() for item in peer_tickers.split(",") if item.strip()]
    else:
        peers = [item.strip() for item in (peer_tickers or []) if str(item).strip()]

    target_info = _market_data_info(market_data)
    if not target_info:
        fetched, error = _fetch_yfinance_info(symbol)
        target_info = fetched
        if error:
            warnings.append(error)

    target_row = _row_from_info(symbol, target_info, screener_data)

    peer_rows: list[dict[str, Any]] = []
    for peer in peers:
        ticker = _ensure_ns(peer)
        if _base_symbol(ticker) == _base_symbol(symbol):
            continue
        info, error = _fetch_yfinance_info(ticker)
        if error:
            warnings.append(error)
            continue
        peer_rows.append(_row_from_info(ticker, info, None))

    peer_stats = _stats(peer_rows, METRIC_COLUMNS)
    warnings.extend(_size_warnings(target_row, peer_rows))

    is_financial = bool(target_row.get("Is Financial"))
    active_columns = [col for col in METRIC_COLUMNS if col != ("D/E" if is_financial else "NIM %")]

    table = []
    for row_type, row in [("Target", target_row), *[("Peer", peer) for peer in peer_rows]]:
        table.append({"Type": row_type, **{key: row.get(key) for key in ["Symbol", "Company", "Sector", *active_columns]}})

    if not peer_rows:
        warnings.append("No peer rows were available. Add manual peer tickers for a useful comparison.")

    return {
        "success": True,
        "source": "yfinance",
        "data": {
            "target": target_row,
            "peers": peer_rows,
            "table": table,
            "peer_stats": peer_stats,
            "valuation_flags": _premium_discount_flags(target_row, peer_stats),
            "is_financial_sector": is_financial,
            "active_columns": active_columns,
        },
        "warnings": warnings,
    }
