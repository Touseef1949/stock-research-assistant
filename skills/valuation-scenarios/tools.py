"""Deterministic scenario calculations bundled with valuation workflows."""

from __future__ import annotations

from typing import Any


def calculate_multiple_scenarios(
    current_price: float,
    forward_metric: float,
    bear_multiple: float,
    base_multiple: float,
    bull_multiple: float,
) -> dict[str, Any]:
    """Calculate scenario values and upside/downside from an earnings or cash metric."""
    price = float(current_price)
    metric = float(forward_metric)
    if price <= 0 or metric <= 0:
        raise ValueError("Current price and forward metric must be positive.")
    scenarios = {}
    for name, multiple in (("bear", bear_multiple), ("base", base_multiple), ("bull", bull_multiple)):
        value = metric * float(multiple)
        scenarios[name] = {
            "multiple": float(multiple),
            "implied_value": value,
            "upside_downside_pct": ((value / price) - 1) * 100,
        }
    return {"current_price": price, "forward_metric": metric, "scenarios": scenarios}
