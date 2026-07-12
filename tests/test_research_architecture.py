"""Tests for progressive skills, research routing, evidence, and tool traces."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.research_router import route_research_query
from core.skills import SkillRegistry, parse_skill_markdown
from research_tools.market_context import (
    evaluate_risk_flags,
    get_market_snapshot,
    get_technical_metrics,
)
from services.research_workflow import prepare_research_workflow
from services import analysis_pipeline


def market_data(source: str = "yfinance", history_rows: int = 100) -> dict:
    return {
        "symbol": "TCS.NS",
        "base_symbol": "TCS",
        "name": "Tata Consultancy Services",
        "price": 4000.0,
        "change": 10.0,
        "change_pct": 0.25,
        "source": source,
        "history": list(range(history_rows)),
        "fundamentals": {
            "market_cap": 14_000_000,
            "trailing_pe": 30.0,
            "forward_pe": 27.0,
            "price_to_book": 12.0,
            "roe": 0.42,
            "revenue_growth": 0.08,
            "profit_margins": 0.19,
            "debt_to_equity": 0.1,
        },
        "technicals": {
            "trend": "Bullish",
            "rsi": 56.0,
            "macd": 12.0,
            "macd_signal": 9.0,
            "ema20": 3950.0,
            "ema50": 3860.0,
            "support": 3850.0,
            "resistance": 4100.0,
            "return_1y_pct": 11.0,
            "max_drawdown_pct": -18.0,
            "volatility_60d_pct": 24.0,
        },
    }


def test_parse_skill_markdown_reads_frontmatter_and_body():
    front, body = parse_skill_markdown(
        "---\nname: demo\ndescription: Demo skill\nrequired_tools: [one, two]\n---\n\nDo the work."
    )
    assert front["name"] == "demo"
    assert front["required_tools"] == ["one", "two"]
    assert body == "Do the work."


def test_registry_discovers_shipped_skills_and_progressively_loads_body():
    registry = SkillRegistry()
    names = {skill.name for skill in registry.list_skills()}
    assert {
        "stock-snapshot",
        "fundamental-quality",
        "technical-entry",
        "peer-valuation",
        "valuation-scenarios",
        "risk-governance",
        "earnings-deep-dive",
        "catalyst-monitor",
        "investment-thesis",
    }.issubset(names)
    assert "procedure" not in registry.catalog()[0]
    loaded = registry.load("/valuation")
    assert loaded is not None
    assert "procedure" in loaded
    assert "get_valuation_inputs" in loaded["required_tools"]


def test_registry_loads_bundled_skill_tools():
    registry = SkillRegistry()
    peer_tools = registry.bundled_tools("peer-valuation")
    result = peer_tools["calculate_peer_premium"](30, [20, 25, 30])
    assert result["peer_median"] == 25
    assert result["premium_discount_pct"] == pytest.approx(20)


def test_registry_handles_invalid_skill_without_breaking_catalog(tmp_path: Path):
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "SKILL.md").write_text("---\nname: broken: yaml:\n---\nbody", encoding="utf-8")
    assert SkillRegistry(tmp_path).list_skills() == []


def test_router_bypasses_skills_for_simple_fact():
    route = route_research_query("What is TCS current price?")
    assert route.mode == "direct"
    assert route.direct_tool == "get_market_snapshot"
    assert route.skills == ()


def test_router_honors_slash_commands_and_multi_step_intent():
    valuation = route_research_query("/valuation TCS")
    thesis = route_research_query("Build a bull and bear thesis for CDSL")
    assert valuation.skills == ("valuation-scenarios",)
    assert thesis.mode == "workflow"
    assert thesis.skills[0] == "investment-thesis"


def test_market_tool_produces_normalized_evidence():
    result = get_market_snapshot(market_data())
    assert result.success is True
    assert result.source == "yfinance"
    assert result.confidence == "high"
    assert any(item.metric == "price" and item.value == 4000.0 for item in result.evidence)
    assert all(item.as_of for item in result.evidence)


def test_fallback_and_short_history_lower_confidence():
    fallback = market_data(source="screener_fallback", history_rows=1)
    result = get_technical_metrics(fallback)
    assert result.confidence == "low"
    assert result.is_fallback is True
    assert any("price history" in warning.lower() for warning in result.warnings)


def test_risk_flags_are_deterministic():
    data = market_data()
    data["fundamentals"]["debt_to_equity"] = 2.5
    data["technicals"]["max_drawdown_pct"] = -40
    result = evaluate_risk_flags(data)
    assert result.data["high_leverage_flag"] is True
    assert result.data["deep_drawdown_flag"] is True


def test_workflow_loads_skill_runs_tools_and_builds_auditable_trace():
    result = prepare_research_workflow("/snapshot TCS", market_data())
    assert result.route.skills == ("stock-snapshot",)
    assert result.loaded_skills[0]["name"] == "stock-snapshot"
    assert {item.tool_name for item in result.tool_results} == {
        "get_market_snapshot",
        "get_fundamental_metrics",
        "get_technical_metrics",
        "evaluate_risk_flags",
    }
    assert result.evidence
    assert any(event.event_type == "skill" for event in result.trace)
    assert any(event.event_type == "tool" for event in result.trace)


def test_workflow_dict_compacts_skill_and_tool_payloads():
    result = prepare_research_workflow("/snapshot TCS", market_data())
    payload = result.to_dict()
    assert "procedure" not in payload["loaded_skills"][0]
    assert payload["loaded_skills"][0]["procedure_excerpt"]
    assert "data" not in payload["tool_results"][0]
    assert payload["tool_results"][0]["data_keys"]


def test_earnings_tools_execute_and_report_source_gaps_without_being_skipped():
    data = market_data()
    data["screener_data"] = {
        "success": True,
        "source": "screener",
        "data": {
            "symbol": "TCS",
            "url": "https://www.screener.in/company/TCS/",
            "years": ["Mar 2026"],
            "quarterly": {"sales": [100]},
            "profit_loss": {"sales": [400]},
            "balance_sheet": {},
            "cash_flow": {},
            "documents": {"transcripts": [], "annual_reports": [], "announcements": []},
        },
        "warnings": [],
    }
    result = prepare_research_workflow("/earnings TCS", data)
    assert not [event for event in result.trace if event.status == "skipped"]
    assert {item.tool_name for item in result.tool_results}.issuperset(
        {"get_filing_results", "get_earnings_transcript"}
    )
    assert any("No earnings transcript link" in warning for warning in result.warnings)


def test_catalyst_workflow_loads_news_filings_transcript_and_consensus_tools(monkeypatch):
    from research_tools import TOOL_FUNCTIONS
    from core.research_contracts import ToolResult

    names = ("get_recent_news", "get_filing_results", "get_earnings_transcript", "get_analyst_consensus")
    originals = {name: TOOL_FUNCTIONS[name] for name in names}
    try:
        for name in names:
            monkeypatch.setitem(
                TOOL_FUNCTIONS,
                name,
                lambda _data, tool_name=name: ToolResult(
                    tool_name=tool_name,
                    success=True,
                    symbol="TCS.NS",
                    source="fixture",
                ),
            )
        result = prepare_research_workflow("/catalysts TCS", market_data())
    finally:
        TOOL_FUNCTIONS.update(originals)
    assert result.route.skills == ("catalyst-monitor",)
    assert {item.tool_name for item in result.tool_results} == set(names)


def test_run_analysis_attaches_backward_compatible_workflow_metadata(monkeypatch):
    data = market_data()
    monkeypatch.setattr(analysis_pipeline, "load_market_data", lambda _symbol: data)
    monkeypatch.setattr(
        analysis_pipeline,
        "run_local_pipeline",
        lambda _data, _reason: {
            "mode": "local",
            "agent_outputs": {},
            "final_report": "Existing report",
            "composite": 5.0,
            "verdict": "WATCH",
            "generated_at": "now",
        },
    )

    returned_data, result = analysis_pipeline.run_analysis(
        "TCS",
        api_key="",
        resolved={"symbol": "TCS.NS"},
    )

    assert returned_data is data
    assert result["base_report"] == "Existing report"
    assert "Evidence-backed observations" in result["final_report"]
    assert result["research_workflow"]["route"]["skills"] == ("stock-snapshot",)
    assert result["research_workflow"]["evidence"]
    assert result["research_validation"]["valid"] is True
