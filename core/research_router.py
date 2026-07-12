"""Deterministic routing between direct data tools and research skills."""

from __future__ import annotations

import re

from core.research_contracts import RouteDecision
from core.skills import SkillRegistry

DIRECT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "get_market_snapshot",
        (
            "current price",
            "share price",
            "market cap",
            "p/e",
            "pe ratio",
            "price to book",
        ),
    ),
    (
        "get_technical_metrics",
        ("rsi", "support", "resistance", "one year return", "1 year return", "52 week"),
    ),
    (
        "get_fundamental_metrics",
        ("roe", "roce", "debt to equity", "revenue growth", "profit margin"),
    ),
)

SKILL_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "catalyst-monitor",
        (
            "catalyst",
            "upcoming event",
            "event calendar",
            "what to watch",
            "news monitor",
        ),
    ),
    (
        "earnings-deep-dive",
        ("earnings", "quarterly result", "results", "guidance", "concall"),
    ),
    (
        "peer-valuation",
        ("compare", "peer", "relative valuation", "competitor", "expensive", "cheap"),
    ),
    (
        "valuation-scenarios",
        (
            "valuation",
            "fair value",
            "target price",
            "dcf",
            "bull case value",
            "bear case value",
        ),
    ),
    (
        "risk-governance",
        ("risk", "governance", "pledge", "auditor", "downside", "red flag"),
    ),
    (
        "technical-entry",
        ("entry", "technical", "momentum", "support", "resistance", "chart"),
    ),
    (
        "fundamental-quality",
        ("fundamental", "quality", "balance sheet", "cash flow", "growth"),
    ),
    (
        "investment-thesis",
        (
            "thesis",
            "bull case",
            "bear case",
            "market missing",
            "research further",
            "attractive",
        ),
    ),
)


def _is_simple_fact(query: str) -> bool:
    words = re.findall(r"[a-z0-9]+", query.lower())
    complex_markers = {
        "analyze",
        "analysis",
        "explain",
        "why",
        "should",
        "report",
        "deep",
        "compare",
    }
    return len(words) <= 14 and not complex_markers.intersection(words)


def route_research_query(
    query: str, registry: SkillRegistry | None = None
) -> RouteDecision:
    registry = registry or SkillRegistry()
    normalized = " ".join((query or "").strip().lower().split())

    if normalized.startswith("/"):
        command = normalized.split()[0]
        skill = registry.get(command)
        if skill:
            return RouteDecision(
                query=query,
                mode="workflow",
                skills=(skill.name,),
                reason=f"Explicit {command} command",
            )

    if _is_simple_fact(normalized):
        for tool_name, phrases in DIRECT_PATTERNS:
            if any(phrase in normalized for phrase in phrases):
                return RouteDecision(
                    query=query,
                    mode="direct",
                    direct_tool=tool_name,
                    reason="Single factual metric request",
                )

    selected: list[str] = []
    for skill_name, phrases in SKILL_PATTERNS:
        if any(phrase in normalized for phrase in phrases) and registry.get(skill_name):
            selected.append(skill_name)

    if "investment-thesis" in selected:
        selected = ["investment-thesis"] + [
            name for name in selected if name != "investment-thesis"
        ]
    if not selected:
        selected = ["stock-snapshot"]

    return RouteDecision(
        query=query,
        mode="workflow",
        skills=tuple(dict.fromkeys(selected)),
        reason=(
            "Matched research workflow intent"
            if selected != ["stock-snapshot"]
            else "Default stock research workflow"
        ),
    )
