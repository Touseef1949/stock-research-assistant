"""Governance scoring helpers for Deep Research."""

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


def _trend(values: list[float], tolerance: float = 0.5) -> str:
    if len(values) < 2:
        return "unavailable"
    change = values[-1] - values[0]
    if change > tolerance:
        return "increasing"
    if change < -tolerance:
        return "decreasing"
    return "stable"


def evaluate_governance(screener_data: dict[str, Any] | None) -> dict[str, Any]:
    """Evaluate ownership quality, pledge risk, and governance score."""
    data = _unwrap(screener_data)
    warnings: list[str] = []

    promoter = _series(data, ["shareholding", "promoter_pct"])
    pledged = _series(data, ["shareholding", "pledged_promoter_pct"])
    fii = _series(data, ["shareholding", "fii_pct"])
    dii = _series(data, ["shareholding", "dii_pct"])
    public = _series(data, ["shareholding", "public_pct"])

    promoter_holding = promoter[-1] if promoter else None
    pledged_pct = pledged[-1] if pledged else None
    fii_holding = fii[-1] if fii else None
    dii_holding = dii[-1] if dii else None
    public_holding = public[-1] if public else None

    flags: list[str] = []
    score = 10.0

    if promoter_holding is None:
        warnings.append("Promoter holding unavailable")
        score -= 1.0
    elif promoter_holding < 30:
        flags.append("Promoter holding below 30%")
        score -= 1.5

    promoter_trend = _trend(promoter)
    if promoter_trend == "decreasing":
        flags.append("Promoter holding trend is decreasing")
        score -= 1.5

    if pledged_pct is None:
        pass  # Pledged promoter data often unavailable from Screener — not an error
    elif pledged_pct > 25:
        flags.append("Promoter pledge above 25%")
        score -= 2.0
    elif pledged_pct > 0:
        flags.append("Promoter pledge exists")
        score -= 0.75

    if fii and _trend(fii) == "decreasing":
        flags.append("FII holding trend is decreasing")
        score -= 0.5
    if dii and _trend(dii) == "decreasing":
        flags.append("DII holding trend is decreasing")
        score -= 0.25

    score = max(0.0, min(10.0, score))

    return {
        "success": True,
        "source": "screener",
        "data": {
            "promoter_holding": promoter_holding,
            "promoter_trend": promoter_trend,
            "promoter_history": promoter,
            "pledged_pct": pledged_pct,
            "fii_holding": fii_holding,
            "fii_trend": _trend(fii),
            "dii_holding": dii_holding,
            "dii_trend": _trend(dii),
            "public_holding": public_holding,
            "governance_score": round(score, 1),
            "flags": flags,
        },
        "warnings": warnings,
    }
