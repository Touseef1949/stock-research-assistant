"""Tests for workflow-controlled synthesis and evidence validation."""

from __future__ import annotations

from core.research_validation import validate_evidence_citations
from services import research_orchestrator
from services import analysis_pipeline


def market_data() -> dict:
    return {
        "symbol": "TCS.NS",
        "name": "TCS",
        "price": 4000.0,
        "change": 10.0,
        "change_pct": 0.25,
        "source": "yfinance",
        "history": list(range(100)),
        "info": {
            "currentPrice": 4000.0,
            "targetMeanPrice": 4400.0,
            "numberOfAnalystOpinions": 20,
            "recommendationKey": "buy",
        },
        "fundamentals": {
            "market_cap": 14_000_000,
            "trailing_pe": 30.0,
            "price_to_book": 12.0,
            "roe": 0.42,
            "revenue_growth": 0.08,
            "debt_to_equity": 0.1,
        },
        "technicals": {
            "trend": "Bullish",
            "rsi": 56.0,
            "support": 3850.0,
            "resistance": 4100.0,
            "return_1y_pct": 11.0,
            "max_drawdown_pct": -18.0,
            "volatility_60d_pct": 24.0,
        },
    }


def test_direct_question_returns_one_deterministic_cited_metric():
    response = research_orchestrator.run_research_request(
        "What is TCS current price?",
        market_data(),
    )
    assert response.synthesis_mode == "direct"
    assert "4,000.00" in response.answer
    assert "TCS.NS-get_market_snapshot-002" in response.answer
    assert response.validation["valid"] is True


def test_workflow_without_api_key_uses_grounded_fallback():
    response = research_orchestrator.run_research_request(
        "/valuation TCS",
        market_data(),
    )
    assert response.synthesis_mode == "fallback"
    assert "Existing coordinated view" not in response.answer
    assert "Evidence-backed observations" in response.answer
    assert response.validation["valid"] is True
    assert any(event.event_type == "synthesis" for event in response.workflow.trace)
    assert any(event.event_type == "validation" for event in response.workflow.trace)


def test_invalid_agent_citation_forces_deterministic_fallback(monkeypatch):
    monkeypatch.setattr(
        research_orchestrator,
        "_agent_answer",
        lambda *args, **kwargs: "TCS trades at P/E 31 [NOT-REAL].",
    )
    response = research_orchestrator.run_research_request(
        "/valuation TCS",
        market_data(),
        api_key="secret",
    )
    assert response.synthesis_mode == "fallback"
    assert "NOT-REAL" not in response.answer
    assert response.validation["valid"] is True
    assert any("did not pass evidence validation" in warning for warning in response.workflow.warnings)


def test_valid_agent_answer_is_preserved(monkeypatch):
    monkeypatch.setattr(
        research_orchestrator,
        "_agent_answer",
        lambda *args, **kwargs: "Current price is 4000 [TCS.NS-get_market_snapshot-002].",
    )
    response = research_orchestrator.run_research_request(
        "/valuation TCS",
        market_data(),
        api_key="secret",
    )
    assert response.synthesis_mode == "agent"
    assert response.validation["valid"] is True


def test_validator_reports_unknown_and_missing_citations():
    workflow = research_orchestrator.prepare_research_workflow("/snapshot TCS", market_data())
    unknown = validate_evidence_citations("Price is 4000 [UNKNOWN].", workflow.evidence)
    missing = validate_evidence_citations("Price is 4000.", workflow.evidence)
    prose = validate_evidence_citations(
        "Management reiterated guidance and margin discipline.",
        workflow.evidence,
        require_citations=True,
    )
    assert unknown["valid"] is False
    assert unknown["invalid_evidence_ids"] == ["UNKNOWN"]
    assert missing["valid"] is False
    assert prose["valid"] is False
    assert "no evidence citations" in missing["warnings"][0]
    assert "no evidence citations" in prose["warnings"][0]


def test_direct_analysis_skips_expensive_agent_pipeline(monkeypatch):
    data = market_data()
    monkeypatch.setattr(analysis_pipeline, "load_market_data", lambda _symbol: data)
    monkeypatch.setattr(
        analysis_pipeline,
        "run_agent_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("agent pipeline must not run")),
    )
    _data, result = analysis_pipeline.run_analysis(
        "TCS",
        api_key="secret",
        resolved={"symbol": "TCS.NS"},
        research_query="What is TCS current price?",
    )
    assert result["research_synthesis_mode"] == "direct"
    assert "4,000.00" in result["final_report"]
    assert "expensive agent synthesis was skipped" in result["base_report"]
