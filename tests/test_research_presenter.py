"""Tests for research workflow UI presentation helpers."""

from services.research_presenter import (
    WORKFLOW_CHOICES,
    build_research_query,
    evidence_rows,
    trace_rows,
    workflow_overview,
)


def sample_workflow():
    return {
        "route": {
            "mode": "workflow",
            "skills": ["valuation-scenarios"],
            "direct_tool": "",
            "reason": "Explicit /valuation command",
        },
        "tool_results": [{"source": "yfinance"}, {"source": "screener"}],
        "evidence": [
            {
                "evidence_id": "TCS-price-001",
                "metric": "price",
                "value": 4000,
                "source": "yfinance",
                "as_of": "2026-07-11",
                "confidence": "high",
                "kind": "market",
            }
        ],
        "trace": [
            {
                "event_type": "skill",
                "name": "valuation-scenarios",
                "status": "completed",
                "detail": "Procedure loaded on demand",
                "timestamp": "2026-07-11",
            }
        ],
        "warnings": ["One field was unavailable"],
    }


def test_workflow_choices_cover_all_shipped_user_workflows():
    assert {
        "Auto-select",
        "Stock snapshot",
        "Fundamental quality",
        "Technical entry",
        "Peer valuation",
        "Valuation scenarios",
        "Risk and governance",
        "Earnings deep dive",
        "Catalyst monitor",
        "Investment thesis",
    } == set(WORKFLOW_CHOICES)


def test_every_workflow_has_a_concise_question_example():
    for choice in WORKFLOW_CHOICES.values():
        assert choice["example"].endswith("?")
        assert len(choice["example"]) <= 80


def test_build_research_query_defaults_to_snapshot_without_question():
    assert build_research_query("TCS", "Auto-select", "") == "/snapshot TCS"


def test_build_research_query_preserves_explicit_workflow_and_context():
    assert build_research_query("TCS", "Valuation scenarios", "What is priced in?") == (
        "/valuation TCS. Decision context: What is priced in?"
    )


def test_build_research_query_auto_routes_free_text():
    assert build_research_query("TCS", "Auto-select", "Is valuation justified?") == (
        "Is valuation justified? for TCS"
    )


def test_workflow_overview_summarizes_sources_evidence_and_warnings():
    overview = workflow_overview(sample_workflow())
    assert overview["skills"] == ["valuation-scenarios"]
    assert overview["evidence_count"] == 1
    assert overview["sources"] == ["screener", "yfinance"]
    assert overview["warnings"] == ["One field was unavailable"]


def test_evidence_and_trace_rows_are_ui_ready():
    workflow = sample_workflow()
    assert evidence_rows(workflow)[0]["Evidence ID"] == "TCS-price-001"
    assert trace_rows(workflow)[0]["Name"] == "valuation-scenarios"


def test_presenter_handles_legacy_or_missing_workflow():
    assert workflow_overview(None)["evidence_count"] == 0
    assert evidence_rows({}) == []
    assert trace_rows(None) == []
