"""Pure presentation helpers for the skill-driven research UI."""

from __future__ import annotations

from typing import Any


WORKFLOW_CHOICES: dict[str, dict[str, str]] = {
    "Auto-select": {
        "command": "",
        "description": "Route the question to the narrowest relevant research workflow.",
    },
    "Stock snapshot": {
        "command": "/snapshot",
        "description": "Market, valuation, quality, momentum, and risk overview.",
    },
    "Fundamental quality": {
        "command": "/fundamentals",
        "description": "Growth, profitability, capital efficiency, leverage, and financial quality.",
    },
    "Technical entry": {
        "command": "/entry",
        "description": "Trend, momentum, support/resistance, volatility, and entry conditions.",
    },
    "Peer valuation": {
        "command": "/peers",
        "description": "Relative valuation with comparable companies and premium/discount logic.",
    },
    "Valuation scenarios": {
        "command": "/valuation",
        "description": "Transparent bear, base, and bull valuation assumptions.",
    },
    "Risk and governance": {
        "command": "/risks",
        "description": "Financial, market, governance, and evidence-quality risks.",
    },
    "Earnings deep dive": {
        "command": "/earnings",
        "description": "Reported results, guidance, operating drivers, and thesis changes.",
    },
    "Catalyst monitor": {
        "command": "/catalysts",
        "description": "Recent evidence, upcoming events, catalyst windows, and monitoring triggers.",
    },
    "Investment thesis": {
        "command": "/thesis",
        "description": "Bull/bear case, variant perception, catalysts, valuation, and falsifiers.",
    },
}


def build_research_query(symbol: str, workflow_label: str, question: str = "") -> str:
    """Build one router query while preserving an explicitly selected workflow."""
    clean_symbol = str(symbol or "").strip().upper()
    clean_question = " ".join(str(question or "").strip().split())
    choice = WORKFLOW_CHOICES.get(workflow_label) or WORKFLOW_CHOICES["Auto-select"]
    command = choice["command"]

    if command:
        context = f"{command} {clean_symbol}".strip()
        return f"{context}. Decision context: {clean_question}" if clean_question else context
    if clean_question:
        return f"{clean_question} for {clean_symbol}" if clean_symbol.lower() not in clean_question.lower() else clean_question
    return f"/snapshot {clean_symbol}".strip()


def workflow_overview(workflow: dict[str, Any] | None) -> dict[str, Any]:
    workflow = workflow if isinstance(workflow, dict) else {}
    route = workflow.get("route") if isinstance(workflow.get("route"), dict) else {}
    skills = route.get("skills") or []
    evidence = workflow.get("evidence") if isinstance(workflow.get("evidence"), list) else []
    tools = workflow.get("tool_results") if isinstance(workflow.get("tool_results"), list) else []
    sources = sorted(
        {
            str(item.get("source"))
            for item in tools
            if isinstance(item, dict) and item.get("source")
        }
    )
    return {
        "mode": str(route.get("mode") or "unavailable"),
        "skills": [str(item) for item in skills],
        "direct_tool": str(route.get("direct_tool") or ""),
        "reason": str(route.get("reason") or ""),
        "evidence_count": len(evidence),
        "sources": sources,
        "warnings": [str(item) for item in workflow.get("warnings") or []],
    }


def evidence_rows(workflow: dict[str, Any] | None) -> list[dict[str, Any]]:
    workflow = workflow if isinstance(workflow, dict) else {}
    rows = []
    for item in workflow.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "Evidence ID": item.get("evidence_id", ""),
                "Metric": item.get("metric", ""),
                "Value": item.get("value"),
                "Source": item.get("source", ""),
                "As of": item.get("as_of", ""),
                "Confidence": item.get("confidence", ""),
                "Type": item.get("kind", ""),
            }
        )
    return rows


def trace_rows(workflow: dict[str, Any] | None) -> list[dict[str, Any]]:
    workflow = workflow if isinstance(workflow, dict) else {}
    rows = []
    for item in workflow.get("trace") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "Action": item.get("event_type", ""),
                "Name": item.get("name", ""),
                "Status": item.get("status", ""),
                "Detail": item.get("detail", ""),
                "Time": item.get("timestamp", ""),
            }
        )
    return rows
