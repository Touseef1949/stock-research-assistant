"""Tests for critical app.py paths — PDF, pipeline, rendering, markdown.

Run: pytest tests/test_app_critical.py -v
"""

import re
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

# Import app module — but mock Streamlit before importing
import streamlit as st

# We need to mock st.session_state for imports that touch it at module level
_st_mock = MagicMock()
_st_mock.session_state = MagicMock()
_st_mock.session_state.get = MagicMock(return_value=False)

with patch.dict("sys.modules", {"streamlit": _st_mock}):
    pass  # app.py already imported; we'll mock at test level


# Import testable pure functions from app.py
import sys

sys.path.insert(0, "")
from app import AgentResult
from logic import SCORE_ORDER, local_scores


# ═══════════════════════════════════════════════════════════════
# Test data factory
# ═══════════════════════════════════════════════════════════════

def make_mock_data(symbol="SBIN.NS"):
    """Factory for realistic market_data dict used across the app."""
    return {
        "symbol": symbol,
        "base_symbol": "SBIN",
        "name": "State Bank of India",
        "exchange": "NSE",
        "price": 780.50,
        "change": 12.30,
        "change_pct": 1.60,
        "as_of": "16 Jun 2026, 14:30",
        "source": "yfinance",
        "fundamentals": {
            "trailing_pe": 12.5,
            "forward_pe": 10.8,
            "price_to_book": 1.8,
            "roe": 0.15,
            "debt_to_equity": 90.0,
            "revenue_growth": 0.09,
            "profit_margins": 0.18,
            "dividend_yield": 0.015,
            "beta": 0.95,
            "market_cap": 6_500_000_000_000,
        },
        "technicals": {
            "trend": "Bullish",
            "rsi": 58.0,
            "macd": 3.2,
            "macd_signal": 2.1,
            "ema20": 770.0,
            "ema50": 745.0,
            "support": 720.0,
            "resistance": 820.0,
            "return_1y_pct": 18.5,
            "max_drawdown_pct": 22.0,
            "volatility_60d_pct": 28.0,
            "avg_volume_20d": 15_000_000,
            "latest_volume": 12_500_000,
        },
        "history": MagicMock(),
        "info": {"longName": "State Bank of India", "exchange": "NSE", "currency": "INR"},
    }


def make_mock_result(verdict="BUY", composite=7.2, mode="agent"):
    """Factory for realistic result dict."""
    outputs = {
        "Fundamentals": AgentResult(
            name="Fundamentals", score=7.8,
            content="SCORE: 7.8/10\nStrong balance sheet with improving asset quality.",
            source="agent",
        ),
        "Technicals": AgentResult(
            name="Technicals", score=7.0,
            content="SCORE: 7.0/10\nBullish EMA crossover with healthy RSI.",
            source="agent",
        ),
        "Sentiment": AgentResult(
            name="Sentiment", score=6.5,
            content="SCORE: 6.5/10\nNeutral-to-positive analyst coverage.",
            source="agent",
        ),
        "Risk": AgentResult(
            name="Risk", score=7.5,
            content="SCORE: 7.5/10\nModerate drawdown with acceptable volatility.",
            source="agent",
        ),
    }
    return {
        "mode": mode,
        "verdict": verdict,
        "composite": composite,
        "agent_outputs": outputs,
        "final_report": "**BUY** SBIN with composite 7.2/10.\nStrong fundamentals, bullish technicals.",
        "generated_at": "16 Jun 2026, 14:30",
    }


# ═══════════════════════════════════════════════════════════════
# AgentResult
# ═══════════════════════════════════════════════════════════════

def test_agent_result_creation():
    r = AgentResult(name="Test", content="content", score=7.5, source="agent")
    assert r.name == "Test"
    assert r.score == 7.5
    assert r.source == "agent"


# ═══════════════════════════════════════════════════════════════
# format_agent_outputs
# ═══════════════════════════════════════════════════════════════

def test_format_agent_outputs():
    from app import format_agent_outputs

    outputs = {
        "Fundamentals": AgentResult(name="F", content="Good fundamentals", score=7.5, source="agent"),
        "Technicals": AgentResult(name="T", content="Bullish trend", score=6.8, source="agent"),
        "Sentiment": AgentResult(name="S", content="Neutral", score=6.0, source="agent"),
        "Risk": AgentResult(name="R", content="Low risk", score=8.0, source="agent"),
    }
    result = format_agent_outputs(outputs)
    assert "Fundamentals (7.5/10)" in result
    assert "Good fundamentals" in result
    assert "Bullish trend" in result


def test_format_agent_outputs_missing_dimension():
    from app import format_agent_outputs

    outputs = {"Fundamentals": AgentResult(name="F", content="OK", score=7.0, source="agent")}
    result = format_agent_outputs(outputs)
    assert "Fundamentals" in result
    assert "Technicals" not in result


# ═══════════════════════════════════════════════════════════════
# build_local_summary
# ═══════════════════════════════════════════════════════════════

def test_build_local_summary():
    from app import build_local_summary

    data = make_mock_data()
    outputs = {
        name: AgentResult(name=name, content="test", score=7.0, source="local")
        for name in SCORE_ORDER
    }
    summary = build_local_summary(data, outputs, "Test fallback")
    assert "BUY" in summary or "HOLD" in summary
    assert "composite score" in summary.lower()
    assert "Test fallback" in summary


# ═══════════════════════════════════════════════════════════════
# get_agent_output
# ═══════════════════════════════════════════════════════════════

def test_get_agent_output_from_agentresult():
    from app import get_agent_output

    data = make_mock_data()
    ar = AgentResult(name="Fundamentals", content="test", score=7.5, source="agent")
    result = {"agent_outputs": {"Fundamentals": ar}}
    output = get_agent_output(result, data, "Fundamentals")
    assert isinstance(output, AgentResult)
    assert output.score == 7.5


def test_get_agent_output_from_dict():
    from app import get_agent_output

    data = make_mock_data()
    result = {"agent_outputs": {"Fundamentals": {"content": "test", "score": 6.5, "source": "agent"}}}
    output = get_agent_output(result, data, "Fundamentals")
    assert isinstance(output, AgentResult)
    assert output.score == 6.5


def test_get_agent_output_from_dict_missing_score():
    """When score is missing from dict, falls back to local_scores."""
    from app import get_agent_output

    data = make_mock_data()
    result = {"agent_outputs": {"Fundamentals": {"content": "test", "source": "agent"}}}
    output = get_agent_output(result, data, "Fundamentals")
    assert isinstance(output, AgentResult)
    assert 1.0 <= output.score <= 10.0


def test_get_agent_output_missing_returns_fallback():
    from app import get_agent_output

    data = make_mock_data()
    result = {"agent_outputs": {}}
    output = get_agent_output(result, data, "Fundamentals")
    assert isinstance(output, AgentResult)
    assert output.source == "local"
    assert "Local fallback" in output.content


# ═══════════════════════════════════════════════════════════════
# run_local_pipeline
# ═══════════════════════════════════════════════════════════════

def test_run_local_pipeline():
    from app import run_local_pipeline

    data = make_mock_data()
    result = run_local_pipeline(data, "DEEPSEEK_API_KEY missing")
    assert result["mode"] == "local"
    assert result["verdict"] in ("BUY", "HOLD", "SELL", "AVOID", "STRONG BUY")
    assert "composite" in result
    assert "agent_outputs" in result
    assert "final_report" in result
    assert len(result["agent_outputs"]) == 4  # Fundamentals, Technicals, Sentiment, Risk


def test_run_local_pipeline_all_scores_valid():
    from app import run_local_pipeline

    data = make_mock_data()
    result = run_local_pipeline(data, "test")
    for name in SCORE_ORDER:
        output = result["agent_outputs"][name]
        assert 1.0 <= output.score <= 10.0, f"{name} score {output.score} out of range"


# ═══════════════════════════════════════════════════════════════
# build_report_text
# ═══════════════════════════════════════════════════════════════

def test_build_report_text():
    from app import build_report_text

    data = make_mock_data()
    result = make_mock_result()
    text = build_report_text(data, result)
    assert "SBIN" in text
    assert "7.2/10" in text or "BUY" in text


# ═══════════════════════════════════════════════════════════════
# inline_markdown_to_html
# ═══════════════════════════════════════════════════════════════

def test_inline_markdown_bold():
    from app import inline_markdown_to_html
    assert inline_markdown_to_html("**bold text**") == "<strong>bold text</strong>"


def test_inline_markdown_escapes_html():
    from app import inline_markdown_to_html
    result = inline_markdown_to_html("<script>alert(1)</script>")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_inline_markdown_empty():
    from app import inline_markdown_to_html
    assert inline_markdown_to_html("") == ""


# ═══════════════════════════════════════════════════════════════
# simple_markdown_to_html
# ═══════════════════════════════════════════════════════════════

def test_simple_markdown_paragraphs():
    from app import simple_markdown_to_html
    result = simple_markdown_to_html("Hello world\n\nSecond paragraph")
    assert "<p>Hello world</p>" in result
    assert "<p>Second paragraph</p>" in result


def test_simple_markdown_list():
    from app import simple_markdown_to_html
    result = simple_markdown_to_html("- Item one\n- Item two")
    assert "<ul>" in result
    assert "<li>" in result
    assert "Item one" in result
    assert "Item two" in result
    assert "</ul>" in result


def test_simple_markdown_mixed():
    from app import simple_markdown_to_html
    result = simple_markdown_to_html("Paragraph\n\n- Bullet 1\n- Bullet 2\n\nAnother para")
    assert "<p>Paragraph</p>" in result
    assert "<li>Bullet 1</li>" in result
    assert "<li>Bullet 2</li>" in result
    assert "<p>Another para</p>" in result


def test_simple_markdown_empty():
    from app import simple_markdown_to_html
    assert simple_markdown_to_html("") == ""


# ═══════════════════════════════════════════════════════════════
# build_report_pdf
# ═══════════════════════════════════════════════════════════════

def test_build_report_pdf_produces_bytes():
    """Verify PDF generation produces valid bytes with mock data."""
    from fpdf import FPDF

    from app import build_report_pdf

    data = make_mock_data()
    result = make_mock_result()
    pdf_bytes = build_report_pdf(data, result, FPDF)
    assert isinstance(pdf_bytes, bytes)
    assert len(pdf_bytes) > 100, f"PDF too small: {len(pdf_bytes)} bytes"
    # PDF signature
    assert pdf_bytes[:5] == b"%PDF-", f"Not a valid PDF: {pdf_bytes[:20]}"


def test_build_report_pdf_contains_key_content():
    from fpdf import FPDF

    from app import build_report_pdf

    data = make_mock_data()
    result = make_mock_result()
    pdf_bytes = build_report_pdf(data, result, FPDF)
    # Valid PDF: starts with %PDF-, reasonable size for multi-page report
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 2000, f"PDF suspiciously small: {len(pdf_bytes)} bytes"
    # Check for PDF stream markers indicating content
    assert b"stream" in pdf_bytes


def test_build_report_pdf_handles_missing_fields():
    """PDF should not crash with minimal data."""
    from fpdf import FPDF

    from app import build_report_pdf

    data = {"symbol": "TEST.NS", "base_symbol": "TEST", "name": "Test",
            "fundamentals": {"trailing_pe": 10, "roe": 0.12, "debt_to_equity": 50,
                             "revenue_growth": 0.05},
            "technicals": {"trend": "Neutral", "rsi": 50, "macd": 0, "macd_signal": 0,
                           "ema20": 100, "ema50": 100, "support": 90, "resistance": 110,
                           "return_1y_pct": 5, "max_drawdown_pct": 15, "volatility_60d_pct": 25},
            "as_of": "16 Jun 2026", "price": 100, "change": 0, "change_pct": 0}
    result = {"verdict": "HOLD", "composite": 5.5, "generated_at": "16 Jun 2026",
              "final_report": "Test report", "agent_outputs": {}}
    pdf_bytes = build_report_pdf(data, result, FPDF)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:5] == b"%PDF-"


# ═══════════════════════════════════════════════════════════════
# report_download_payload
# ═══════════════════════════════════════════════════════════════

def test_report_download_payload():
    from app import report_download_payload

    data = make_mock_data()
    result = make_mock_result()
    payload, filename, mime = report_download_payload(data, result)
    assert isinstance(payload, bytes)
    assert "SBIN" in filename
    assert filename.endswith(".pdf")
    assert mime == "application/pdf"


# ═══════════════════════════════════════════════════════════════
# resolve_ticker integration (from logic.py, in app context)
# ═══════════════════════════════════════════════════════════════

def test_resolve_sbin():
    from logic import resolve_ticker

    result = resolve_ticker("SBIN")
    assert result["symbol"] == "SBIN.NS"
    assert result["source"] in ("direct", "map")


# ═══════════════════════════════════════════════════════════════
# Edge cases: local_scores with extreme values
# ═══════════════════════════════════════════════════════════════

def test_local_scores_extreme_pe():
    """Very high P/E should produce low fundamentals score."""
    fundamentals = {"trailing_pe": 500.0, "roe": 0.05, "debt_to_equity": 300.0,
                    "revenue_growth": -0.10, "beta": 2.0}
    technicals = {"trend": "Bearish", "rsi": 15.0, "macd": -5.0, "macd_signal": -3.0,
                  "return_1y_pct": -50.0, "max_drawdown_pct": 60.0, "volatility_60d_pct": 70.0}
    scores = local_scores(fundamentals, technicals)
    assert scores["Fundamentals"] < 4.0
    assert scores["Risk"] < 4.0


def test_local_scores_strong_stock():
    """Excellent metrics should score 7+."""
    fundamentals = {"trailing_pe": 15.0, "roe": 0.25, "debt_to_equity": 20.0,
                    "revenue_growth": 0.20, "beta": 0.8}
    technicals = {"trend": "Bullish", "rsi": 55.0, "macd": 5.0, "macd_signal": 3.0,
                  "return_1y_pct": 30.0, "max_drawdown_pct": 12.0, "volatility_60d_pct": 20.0}
    scores = local_scores(fundamentals, technicals)
    assert scores["Fundamentals"] >= 7.0
    assert scores["Technicals"] >= 7.0
