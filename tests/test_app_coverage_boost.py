"""Extra AppTest coverage for the main app flow and sidebar branches.

Run:
    python3 -m pytest tests/test_app_coverage_boost.py -v --tb=short --timeout=120
"""

from __future__ import annotations

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture()
def app_auth(monkeypatch) -> AppTest:
    """Authenticated AppTest state with Supabase/payment primitives stubbed."""
    import payment

    class AuthResponse:
        session = object()
        user = type("User", (), {"id": "test-user"})()

    monkeypatch.setattr(payment, "_supabase_offline", lambda: True)
    monkeypatch.setattr(payment, "send_otp", lambda email: True)
    monkeypatch.setattr(payment, "verify_otp", lambda email, token: AuthResponse())
    monkeypatch.setattr(payment, "_ensure_user_row", lambda email, user_id=None: None)
    monkeypatch.setattr(
        payment,
        "get_user",
        lambda email: {
            "email": email,
            "plan": "free",
            "analyses_used": 0,
            "analyses_limit": 5,
        },
    )
    monkeypatch.setattr(payment, "load_auth", lambda: None)
    monkeypatch.setattr(payment, "save_auth", lambda email: None)
    monkeypatch.setattr(payment, "clear_auth", lambda: None)

    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    at.session_state["_auth_verified"] = True
    at.session_state["user_email"] = "test@example.com"
    at.run(timeout=60)
    return at


@pytest.fixture()
def app_auth_pipeline(monkeypatch) -> tuple[AppTest, list[dict]]:
    """Authenticated app with the expensive analysis pipeline mocked before import."""
    import logic
    import payment
    import services.analysis_pipeline as analysis_pipeline

    calls: list[dict] = []

    class AuthResponse:
        session = object()
        user = type("User", (), {"id": "test-user"})()

    def fake_run_analysis(symbol, api_key="", progress_callback=None, resolved=None):
        calls.append(
            {
                "symbol": symbol,
                "api_key": api_key,
                "resolved": resolved,
            }
        )
        if progress_callback is not None:
            progress_callback(45, "Running AI analysis")
            progress_callback(90, "Generating report")
        data = {
            "symbol": "SBIN.NS",
            "base_symbol": "SBIN",
            "name": "State Bank of India",
            "exchange": "NSE",
            "as_of": "2026-06-21",
            "price": 750.0,
            "change": 4.0,
            "change_pct": 0.54,
            "source": "mock",
            "fundamentals": {
                "market_cap": 1000000000,
                "trailing_pe": 12.5,
            },
            "technicals": {
                "rsi": 58,
                "trend": "Uptrend",
                "return_1y_pct": 15.2,
            },
            "history": pd.DataFrame(
                {
                    "Open": [740.0, 744.0],
                    "High": [752.0, 756.0],
                    "Low": [735.0, 741.0],
                    "Close": [748.0, 750.0],
                },
                index=pd.to_datetime(["2026-06-20", "2026-06-21"]),
            ),
        }
        result = {
            "verdict": "BUY",
            "composite": 7.4,
            "generated_at": "2026-06-21",
            "mode": "mock",
            "final_report": "Mocked SBI report generated without external agents.",
            "agent_outputs": {
                name: {
                    "content": f"{name} mock notes for SBI.",
                    "score": 7.4,
                    "source": "mock",
                }
                for name in ("Fundamentals", "Technicals", "Sentiment", "Risk")
            },
        }
        return data, result

    monkeypatch.setattr(payment, "_supabase_offline", lambda: True)
    monkeypatch.setattr(payment, "send_otp", lambda email: True)
    monkeypatch.setattr(payment, "verify_otp", lambda email, token: AuthResponse())
    monkeypatch.setattr(payment, "_ensure_user_row", lambda email, user_id=None: None)
    monkeypatch.setattr(
        payment,
        "get_user",
        lambda email: {
            "email": email,
            "plan": "free",
            "analyses_used": 0,
            "analyses_limit": 5,
        },
    )
    monkeypatch.setattr(payment, "load_auth", lambda: None)
    monkeypatch.setattr(payment, "save_auth", lambda email: None)
    monkeypatch.setattr(payment, "clear_auth", lambda: None)
    monkeypatch.setattr(payment, "require_payment", lambda email: True)
    monkeypatch.setattr(payment, "track_usage", lambda email, event: calls.append({"usage": event, "email": email}))
    monkeypatch.setattr(logic, "resolve_ticker", lambda symbol: {"symbol": "SBIN.NS", "name": "State Bank of India"})
    monkeypatch.setattr(analysis_pipeline, "run_analysis", fake_run_analysis)

    at = AppTest.from_file("app.py")
    at.run(timeout=60)
    at.session_state["_auth_verified"] = True
    at.session_state["user_email"] = "test@example.com"
    at.session_state["symbol_input"] = "SBIN"
    at.run(timeout=60)
    return at, calls


def test_hero_analyze_runs_mocked_pipeline_and_renders_result(app_auth_pipeline):
    at, calls = app_auth_pipeline

    at.button(key="hero_analyze_button").click().run(timeout=120)

    assert calls[0]["symbol"] == "SBIN"
    assert calls[0]["resolved"]["symbol"] == "SBIN.NS"
    assert at.session_state["sra_market_data"]["base_symbol"] == "SBIN"
    assert at.session_state["sra_result"]["verdict"] == "BUY"
    assert at.session_state["sra_report_history"][0]["symbol"] == "SBIN"
    assert any(call.get("usage") == "stock_research" for call in calls)
    rendered = "\n".join(str(markdown.value) for markdown in at.markdown)
    assert "Mocked SBI report generated without external agents." in rendered


def test_sidebar_theme_toggle_branch(app_auth: AppTest):
    assert app_auth.session_state["theme"] == "light"

    app_auth.button(key="theme_toggle").click().run(timeout=60)

    assert app_auth.session_state["theme"] == "dark"


def test_sidebar_history_branch_renders_download_and_load_warning(monkeypatch, app_auth: AppTest):
    import services.report_history as report_history_service

    history_item = {
        "symbol": "SBIN",
        "name": "State Bank of India",
        "verdict": "BUY",
        "score": 7.4,
        "time": "21 Jun 2026",
        "timestamp": "missing-report",
        "email": "test@example.com",
    }
    monkeypatch.setattr(report_history_service, "load_history_items", lambda *args, **kwargs: [history_item])
    monkeypatch.setattr(
        report_history_service,
        "report_payload_from_history",
        lambda *args, **kwargs: (b"mock report", "SBIN_analysis.txt", "text/plain"),
    )
    app_auth.session_state["_history_email"] = ""
    app_auth.run(timeout=60)

    assert app_auth.button(key="hist_btn_SBIN_missing-report").label.startswith("SBIN · BUY")
    # st.download_button not directly exposed in AppTest — verify button renders instead

    app_auth.button(key="hist_btn_SBIN_missing-report").click().run(timeout=60)

    assert any("Saved report could not be loaded" in str(w.value) for w in app_auth.warning)


def test_sample_report_preview_renders_for_selected_symbol(app_auth: AppTest):
    app_auth.text_input(key="symbol_input").set_value("RELIANCE").run(timeout=60)

    rendered = "\n".join(str(markdown.value) for markdown in app_auth.markdown)

    assert "Sample report" in rendered
    assert "RELIANCE / Reliance Industries" in rendered
    assert "Integrated operations + scale moat" in rendered


def test_sample_report_preview_falls_back_for_unknown_symbol(app_auth: AppTest):
    app_auth.text_input(key="symbol_input").set_value("MYSTERY").run(timeout=60)

    rendered = "\n".join(str(markdown.value) for markdown in app_auth.markdown)

    assert "MYSTERY / Infosys" in rendered
    assert "Macro/sector risk specific to the company" in rendered
