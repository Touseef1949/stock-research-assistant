"""Plotly financial trend builders for Deep Research."""

from __future__ import annotations

import json
from typing import Any

try:
    import plotly.graph_objects as go
except Exception:  # pragma: no cover
    go = None  # type: ignore[assignment]


COLORS = {
    "green": "#22c55e",
    "red": "#ef4444",
    "blue": "#38bdf8",
    "amber": "#f59e0b",
    "purple": "#a78bfa",
}


def _unwrap_screener(screener_data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(screener_data, dict):
        return {}
    return screener_data.get("data") if isinstance(screener_data.get("data"), dict) else screener_data


def _series(data: dict[str, Any], path: list[str]) -> list[float | None]:
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict):
            return []
        cursor = cursor.get(key)
    if not isinstance(cursor, list):
        return []
    values: list[float | None] = []
    for item in cursor:
        try:
            values.append(float(item) if item is not None else None)
        except Exception:
            values.append(None)
    return values


def _years(data: dict[str, Any], length: int) -> list[str]:
    labels = data.get("years") if isinstance(data.get("years"), list) else []
    labels = [str(label) for label in labels][-length:]
    if len(labels) == length:
        return labels
    return [f"Y-{length-index-1}" if index < length - 1 else "Latest" for index in range(length)]


def _figure_json(fig: Any) -> dict[str, Any]:
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#09111f",
        plot_bgcolor="#09111f",
        font={"color": "#e5e7eb"},
        margin={"l": 32, "r": 24, "t": 52, "b": 36},
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1},
    )
    return json.loads(fig.to_json())


def _has_values(*series: list[float | None]) -> bool:
    return any(any(value is not None for value in values) for values in series)


def build_financial_trends(screener_data: dict[str, Any] | None, market_data: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build dark-theme Plotly figures from Screener financial series."""
    warnings: list[str] = []
    if go is None:
        return {"success": False, "source": "plotly", "data": None, "warnings": ["plotly is not available"]}

    data = _unwrap_screener(screener_data)
    if not data:
        return {"success": True, "source": "screener", "data": {"figures": {}, "summary": []}, "warnings": ["No Screener data available for trend charts"]}

    sales = _series(data, ["profit_loss", "sales"])
    net_profit = _series(data, ["profit_loss", "net_profit"])
    opm = _series(data, ["profit_loss", "opm_pct"])
    eps = _series(data, ["profit_loss", "eps"])
    de = _series(data, ["ratio_series", "debt_to_equity"])
    roe = _series(data, ["ratio_series", "roe_pct"])
    roce = _series(data, ["ratio_series", "roce_pct"])
    ocf = _series(data, ["cash_flow", "operating_cash_flow"])
    pat = net_profit

    max_len = max([len(sales), len(net_profit), len(opm), len(eps), len(de), len(roe), len(roce), len(ocf), 1])
    years = _years(data, max_len)

    def x_for(values: list[float | None]) -> list[str]:
        return years[-len(values):] if values else []

    figures: dict[str, Any] = {}

    if _has_values(sales, net_profit):
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Revenue", x=x_for(sales), y=sales, marker_color=COLORS["blue"]))
        fig.add_trace(go.Bar(name="Net Profit", x=x_for(net_profit), y=net_profit, marker_color=COLORS["green"]))
        fig.update_layout(title="Revenue vs Net Profit", barmode="group", yaxis_title="₹ crore / reported units")
        figures["revenue_vs_net_profit"] = _figure_json(fig)
    else:
        warnings.append("Revenue/Net Profit trend unavailable")

    if _has_values(opm):
        fig = go.Figure()
        fig.add_trace(go.Scatter(name="OPM %", x=x_for(opm), y=opm, mode="lines+markers", line={"color": COLORS["amber"], "width": 3}))
        fig.update_layout(title="Operating Margin Trend", yaxis_title="OPM %")
        figures["opm_trend"] = _figure_json(fig)
    else:
        pass  # OPM not available — common for financials; chart simply omitted

    if _has_values(roe, roce):
        fig = go.Figure()
        fig.add_trace(go.Scatter(name="ROE %", x=x_for(roe), y=roe, mode="lines+markers", line={"color": COLORS["purple"], "width": 3}))
        fig.add_trace(go.Scatter(name="ROCE %", x=x_for(roce), y=roce, mode="lines+markers", line={"color": COLORS["green"], "width": 3}))
        fig.update_layout(title="ROE / ROCE Trend", yaxis_title="%")
        figures["roe_roce_trend"] = _figure_json(fig)
    else:
        warnings.append("ROE/ROCE trend unavailable")

    if _has_values(eps):
        fig = go.Figure()
        fig.add_trace(go.Bar(name="EPS", x=x_for(eps), y=eps, marker_color=COLORS["blue"]))
        fig.update_layout(title="EPS Trend", yaxis_title="EPS")
        figures["eps_trend"] = _figure_json(fig)
    else:
        warnings.append("EPS trend unavailable")

    if _has_values(de):
        fig = go.Figure()
        fig.add_trace(go.Scatter(name="D/E", x=x_for(de), y=de, mode="lines+markers", line={"color": COLORS["red"], "width": 3}))
        fig.update_layout(title="Debt-to-Equity Trend", yaxis_title="D/E")
        figures["debt_equity_trend"] = _figure_json(fig)
    else:
        pass  # D/E not available — normal for financials; chart simply omitted

    if _has_values(ocf, pat):
        fig = go.Figure()
        fig.add_trace(go.Bar(name="OCF", x=x_for(ocf), y=ocf, marker_color=COLORS["green"]))
        fig.add_trace(go.Bar(name="PAT", x=x_for(pat), y=pat, marker_color=COLORS["purple"]))
        fig.update_layout(title="Operating Cash Flow vs PAT", barmode="group", yaxis_title="₹ crore / reported units")
        figures["ocf_vs_pat"] = _figure_json(fig)
    else:
        warnings.append("OCF vs PAT chart unavailable")

    summary = [
        {"metric": "Latest Sales", "value": sales[-1] if sales else None},
        {"metric": "Latest Net Profit", "value": net_profit[-1] if net_profit else None},
        {"metric": "Latest OPM %", "value": opm[-1] if opm else None},
        {"metric": "Latest EPS", "value": eps[-1] if eps else None},
    ]

    return {"success": True, "source": "screener", "data": {"figures": figures, "summary": summary}, "warnings": warnings}
