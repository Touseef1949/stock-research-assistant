"""Deterministic calculations bundled with the peer-valuation skill."""

from __future__ import annotations

from statistics import median
from typing import Any


def calculate_peer_premium(subject_value: float, peer_values: list[float]) -> dict[str, Any]:
    """Return peer median and the subject's percentage premium or discount."""
    clean = sorted(float(value) for value in peer_values if value is not None and float(value) > 0)
    if not clean:
        raise ValueError("At least one positive peer value is required.")
    peer_median = median(clean)
    premium_pct = ((float(subject_value) / peer_median) - 1) * 100
    return {
        "subject_value": float(subject_value),
        "peer_median": peer_median,
        "premium_discount_pct": premium_pct,
        "peer_count": len(clean),
    }
