"""Additional coverage for remaining pure app/deep-research branches."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest


class SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def fake_st():
    st = MagicMock()
    st.session_state = SessionState()
    st.sidebar = Ctx()
    st.button.return_value = False
    st.columns.side_effect = lambda spec, *a, **k: [Ctx() for _ in range(spec if isinstance(spec, int) else len(spec))]
    st.empty.return_value = MagicMock(container=lambda: Ctx(), empty=lambda: None, markdown=lambda *a, **k: None)
    return st


def test_thesis_agent_deepseek_success_and_failures(monkeypatch):
    import deep_research.thesis_agent as ta

    class FakeDeepSeek:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeAgent:
        content = json.dumps(
            {
                "one_line_thesis": "Good",
                "company_overview": "Overview",
                "bull_case": ["B1", "B2", "B3", "B4", "B5", "B6"],
                "bear_case": ["R1"],
                "key_catalysts": ["K1"],
                "market_missing": "M",
            }
        )

        def __init__(self, **kwargs):
            pass

        def run(self, prompt):
            return types.SimpleNamespace(content=self.content)

    monkeypatch.setitem(sys.modules, "agno", types.ModuleType("agno"))
    agent_mod = types.ModuleType("agno.agent")
    agent_mod.Agent = FakeAgent
    deepseek_mod = types.ModuleType("agno.models.deepseek")
    deepseek_mod.DeepSeek = FakeDeepSeek
    models_mod = types.ModuleType("agno.models")
    monkeypatch.setitem(sys.modules, "agno.agent", agent_mod)
    monkeypatch.setitem(sys.modules, "agno.models", models_mod)
    monkeypatch.setitem(sys.modules, "agno.models.deepseek", deepseek_mod)

    empty = {}
    ok = ta.generate_investment_thesis("SBIN", empty, empty, empty, empty, empty, empty, api_key="sk-test")
    assert ok["source"] == "deepseek"
    assert ok["data"]["bull_case"] == ["B1", "B2", "B3", "B4", "B5"]

    FakeAgent.content = "not json"
    fallback = ta.generate_investment_thesis("SBIN", empty, empty, empty, empty, empty, empty, api_key="sk-test")
    assert fallback["source"] == "fallback"
    assert "not valid JSON" in fallback["warnings"][0]

    class RaisingAgent(FakeAgent):
        def run(self, prompt):
            raise RuntimeError("boom")

    agent_mod.Agent = RaisingAgent
    failed = ta.generate_investment_thesis("SBIN", empty, empty, empty, empty, empty, empty, api_key="sk-test")
    assert failed["source"] == "fallback"
    assert "boom" in failed["warnings"][0]


def test_deep_research_orchestrator_helpers_and_pipeline(monkeypatch):
    import deep_research as dr

    assert dr._normalize_peer_tickers(None) == []
    assert dr._normalize_peer_tickers("sbin, hdfcbank.ns, sbin") == ["SBIN.NS", "HDFCBANK.NS"]
    assert dr._merge_warnings({"warnings": ["a", "b"]}, {"warnings": ["a", "c"]}) == ["a", "b", "c"]
    assert dr.run_deep_research("", {})["success"] is False

    def section(name):
        return {"success": True, "data": {"name": name}, "warnings": [f"{name} warn"]}

    monkeypatch.setattr(dr, "fetch_screener_financials", lambda symbol: {"success": False, "warnings": ["screen fail"], "data": {}})
    monkeypatch.setattr(dr, "build_peer_comparison", lambda *a, **k: section("peer"))
    monkeypatch.setattr(dr, "fetch_analyst_targets", lambda *a, **k: section("targets"))
    monkeypatch.setattr(dr, "build_financial_trends", lambda *a, **k: section("trends"))
    monkeypatch.setattr(dr, "evaluate_risk_flags", lambda *a, **k: section("risk"))
    monkeypatch.setattr(dr, "build_valuation_model", lambda *a, **k: section("valuation"))
    monkeypatch.setattr(dr, "evaluate_governance", lambda *a, **k: section("gov"))
    monkeypatch.setattr(dr, "generate_investment_thesis", lambda *a, **k: section("thesis"))
    result = dr.run_deep_research("sbin", {"price": 1}, peer_tickers="hdfcbank")
    assert result["success"] is True
    assert result["symbol"] == "SBIN.NS"
    assert result["peer_tickers"] == ["HDFCBANK.NS"]
    assert "screen fail" in result["warnings"]
    assert result["sections"]["thesis"]["data"]["name"] == "thesis"


def test_app_report_history_and_json_helpers(tmp_path, monkeypatch):
    import app

    st = fake_st()
    st.session_state.user_email = "user@example.com"
    st.session_state.sra_report_history = []
    monkeypatch.setattr(app, "st", st)
    monkeypatch.setattr(app, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(app, "MAX_REPORT_FILES", 2)

    assert app.report_file_symbol("A/B C.NS") == "A_B_C_NS"
    assert app.report_file_symbol("!!!") == "stock"
    assert app.timestamp_from_report_path(Path("SBIN_20260617_120000.json")) == "20260617_120000"
    assert app.timestamp_from_report_path(Path("bad.json")) == ""
    assert app.report_path_for("SBIN.NS", "20260617_120000").name == "SBIN_NS_20260617_120000.json"

    ar = app.AgentResult("F", "content", 7.5, "agent")
    frame = pd.DataFrame({"Date": pd.date_range("2026-01-01", periods=2), "Close": [1.0, 2.0]})
    safe = app.json_safe({"ar": ar, "df": frame, "nan": float("nan"), "ts": pd.Timestamp("2026-01-01")})
    assert safe["ar"]["score"] == 7.5
    restored = app.restore_dataframe(safe["df"])
    assert list(restored["Close"]) == [1.0, 2.0]
    assert app.read_report_file(tmp_path / "missing.json") is None

    data = {"base_symbol": "SBIN", "symbol": "SBIN.NS", "name": "SBI", "history": frame}
    result = {
        "verdict": "BUY",
        "composite": 7.2,
        "generated_at": "now",
        "agent_outputs": {"Fundamentals": ar},
    }
    saved = app.save_report(data, result, email="user@example.com")
    assert saved and Path(saved["path"]).exists()
    app.load_history_from_disk()
    assert len(st.session_state.sra_report_history) == 1
    assert app.load_report("SBIN", st.session_state.sra_report_history[0]["timestamp"]) is True
    assert st.session_state.sra_market_data["base_symbol"] == "SBIN"
    # Exercise the payload path; minimal test data may legitimately fail PDF rendering and return None.
    app.report_payload_from_history(st.session_state.sra_report_history[0])

    app.add_history(data, result)
    assert st.session_state.sra_report_history[0]["symbol"] == "SBIN"

    # Cap enforcement deletes old files beyond MAX_REPORT_FILES.
    for idx in range(4):
        p = tmp_path / f"OLD_{idx}_20260617_12000{idx}.json"
        p.write_text("{}", encoding="utf-8")
    app.enforce_report_cap()
    assert len(list(tmp_path.glob("*.json"))) <= 2


def test_app_lightweight_render_helpers(monkeypatch):
    import app

    st = fake_st()
    st.button.return_value = True
    monkeypatch.setattr(app, "st", st)
    app.render_empty_preview()
    assert st.markdown.called
    assert app.render_hero_action("SBIN") is True
    assert st.button.call_args.kwargs["disabled"] is False
    app.render_analysis_progress_shell("Assessing risk")
    assert st.markdown.call_count >= 3


def test_peer_analysis_edge_helpers(monkeypatch):
    from deep_research import peer_analysis as pa

    assert pa._ensure_ns("") == ""
    assert pa._base_symbol("sbin.bo") == "SBIN"
    assert pa._safe_float("1,234%") == 1234.0
    assert pa._safe_float(object()) is None
    assert pa._get_nested({"a": {"b": 2}}, ["a", "b"]) == 2
    assert pa._get_nested({"a": {}}, ["a", "missing"], "x") == "x"
    assert pa._market_data_info({"fundamentals": {"roe": 1}}) == {"roe": 1}
    assert pa._last_value([None, "bad", "12.5"]) == 12.5
    assert pa._infer_financial_sector("SBIN", {"sector": "Banking"}) is True
    assert pa._stats([], ["P/E"])["P/E"]["median"] is None
    flags = pa._premium_discount_flags({"P/E": 12}, {"P/E": {"median": 10}})
    assert flags[0]["label"] == "premium"
    warnings = pa._size_warnings({"Market Cap": 100}, [{"Symbol": "BIG", "Market Cap": 2000}, {"Symbol": "SMALL", "Market Cap": 5}])
    assert len(warnings) == 2

    monkeypatch.setattr(pa, "_fetch_yfinance_info", lambda symbol: ({"longName": symbol, "marketCap": 10, "trailingPE": 5}, None))
    result = pa.build_peer_comparison("SBIN.NS", "SBIN,HDFCBANK", {}, None)
    assert result["success"] is True
    assert result["data"]["peers"][0]["Symbol"] == "HDFCBANK.NS"


def test_screener_client_fallback_and_fetch_paths(monkeypatch):
    from deep_research import screener_client as sc

    assert sc._clean_symbol(" sbin.ns ") == "SBIN"
    assert sc._strip_tags("<style>x</style><b>A&nbsp;B</b>") == "A B"
    assert sc._to_number("(1,234 Cr.)") == -1234.0
    assert sc._to_number("50L") == 0.5
    assert sc._extract_section('<section id="profit-loss"><p>x</p></section>', "profit-loss") == "<p>x</p>"
    rows = sc._parse_table("<tr><th>Sales</th><td>1</td><td>2</td></tr>")
    assert rows["sales"] == [1.0, 2.0]
    assert sc._find_row(rows, ["sales"]) == [1.0, 2.0]
    assert sc._extract_years("<th>Mar 2024</th><th>TTM</th>") == ["Mar 2024", "TTM"]
    assert sc._growth_from_series([100, 121], 1) == pytest.approx(21.0)

    monkeypatch.setattr(sc, "requests", None)
    assert sc._fetch_html("http://x", 1)[0] is False

    fake_requests = MagicMock()
    fake_requests.get.return_value = types.SimpleNamespace(status_code=404, text="")
    monkeypatch.setattr(sc, "requests", fake_requests)
    assert sc._fetch_html("http://x", 1)[0] is False
    fake_requests.get.return_value = types.SimpleNamespace(status_code=200, text="<html>ok</html>")
    assert sc._fetch_html("http://x", 1) == (True, "<html>ok</html>", None)
    fake_requests.get.side_effect = RuntimeError("net")
    assert sc._fetch_html("http://x", 1)[0] is False

    monkeypatch.setattr("yf_client.ticker_info", lambda symbol: {"marketCap": 100, "currentPrice": 10, "returnOnEquity": 0.2})
    fallback = sc._fallback_from_yfinance("SBIN.NS")
    assert fallback["success"] is True
    monkeypatch.setattr("yf_client.ticker_info", lambda symbol: {})
    assert sc._fallback_from_yfinance("SBIN.NS")["success"] is False


def rich_market_data():
    return {
        "symbol": "SBIN.NS",
        "base_symbol": "SBIN",
        "name": "SBI",
        "exchange": "NSE",
        "source": "yfinance",
        "price": 780.0,
        "fundamentals": {
            "market_cap": 1000000,
            "trailing_pe": 12.0,
            "forward_pe": 10.0,
            "price_to_book": 1.5,
            "roe": 0.15,
            "revenue_growth": 0.1,
            "profit_margins": 0.2,
            "debt_to_equity": 50,
        },
        "technicals": {
            "rsi": 55,
            "trend": "Bullish",
            "return_1y_pct": 12,
            "ema20": 770,
            "ema50": 750,
            "support": 700,
            "resistance": 820,
            "volatility_60d_pct": 20,
        },
        "history": pd.DataFrame({"Close": [1, 2, 3]}),
    }


def rich_result(app):
    return {
        "verdict": "BUY",
        "composite": 7.2,
        "generated_at": "now",
        "mode": "local",
        "final_report": "Final report",
        "agent_outputs": {name: app.AgentResult(name, "content", 7.0, "local") for name in app.SCORE_ORDER},
    }


def configure_rich_streamlit(st):
    st.tabs.side_effect = lambda labels: [Ctx() for _ in labels]
    st.container.return_value = Ctx()
    st.expander.return_value = Ctx()
    st.download_button.return_value = None
    st.text_input.return_value = ""
    return st


def test_render_result_free_and_pro_paths(monkeypatch):
    import app

    data = rich_market_data()
    result = rich_result(app)

    st = configure_rich_streamlit(fake_st())
    st.session_state.user_email = "free@example.com"
    monkeypatch.setattr(app, "st", st)
    monkeypatch.setattr(app, "stock_header_card", lambda d: None)
    monkeypatch.setattr(app, "executive_verdict_strip", lambda d, r: None)
    monkeypatch.setattr(app, "section_title", lambda title: None)
    monkeypatch.setattr(app, "score_card", lambda *a, **k: None)
    monkeypatch.setattr(app, "render_verdict", lambda r: None)
    monkeypatch.setattr(app, "render_chart", lambda d: None)
    monkeypatch.setattr(app, "kpi_card", lambda *a, **k: None)
    monkeypatch.setattr(app, "report_download_payload", lambda d, r: (b"pdf", "r.pdf", "application/pdf"))
    monkeypatch.setattr(app, "get_user", lambda email: {"plan": "free"})
    monkeypatch.setattr("payment._render_upgrade_ui", lambda email, plan: None)
    app.render_result(data, result)
    assert st.warning.called and st.info.called

    st2 = configure_rich_streamlit(fake_st())
    st2.session_state.user_email = "pro@example.com"
    monkeypatch.setattr(app, "st", st2)
    deep_called = []
    monkeypatch.setattr(app, "get_user", lambda email: {"plan": "pro"})
    monkeypatch.setattr(app, "render_deep_research_tab", lambda d, r, symbol: deep_called.append(symbol))
    app.render_result(data, result)
    assert deep_called == ["SBIN.NS"]


def test_render_deep_research_tab_placeholder_existing_and_run(monkeypatch):
    import app

    data = rich_market_data()
    quick = rich_result(app)
    deep_payload = {
        "peer_comparison": {"data": {"table": []}},
        "analyst_targets": {"data": {}},
        "financial_trends": {"data": {"figures": {}}},
        "risk_flags": {"data": {"flags": []}},
        "valuation": {"data": {"methods": []}},
        "governance": {"data": {}},
        "thesis": {"data": {}},
    }

    st = configure_rich_streamlit(fake_st())
    st.session_state.sra_deep_research = {}
    st.button.return_value = False
    monkeypatch.setattr(app, "st", st)
    placeholder_calls = []
    monkeypatch.setattr(app, "_render_deep_placeholder", lambda: placeholder_calls.append(True))
    app.render_deep_research_tab(data, quick, "SBIN")
    assert placeholder_calls == [True]

    st2 = configure_rich_streamlit(fake_st())
    st2.session_state.deep_research = True
    st2.session_state.sra_deep_research = {"SBIN.NS": deep_payload}
    st2.button.return_value = False
    monkeypatch.setattr(app, "st", st2)
    calls = []
    for name in ["_render_peer_comparison", "_render_analyst_targets", "_render_financial_trends", "_render_risk_flags", "_render_valuation", "_render_governance", "_render_thesis"]:
        monkeypatch.setattr(app, name, lambda section, n=name: calls.append(n))
    monkeypatch.setattr(app, "_render_enhanced_pdf", lambda *a: calls.append("pdf"))
    app.render_deep_research_tab(data, quick, "SBIN")
    assert "_render_peer_comparison" in calls and "pdf" in calls

    st3 = configure_rich_streamlit(fake_st())
    st3.session_state.deep_research = True
    st3.session_state.sra_deep_research = {}
    st3.button.return_value = True
    monkeypatch.setattr(app, "st", st3)
    monkeypatch.setattr(app, "_deep_get_api_key", lambda: "sk")
    monkeypatch.setattr(app, "run_deep_research", lambda *a, **k: {**deep_payload, "warnings": ["warn"]})
    app.render_deep_research_tab(data, quick, "SBIN")
    assert st3.success.called
    assert st3.session_state.sra_deep_research["SBIN.NS"]["warnings"] == ["warn"]


def test_run_analysis_and_agent_fallback(monkeypatch):
    import app
    import services.analysis_pipeline as ap
    from services.analysis_pipeline import agent_or_fallback

    data = rich_market_data()
    local = rich_result(app)
    monkeypatch.setattr(ap, "load_market_data", lambda symbol: data)
    monkeypatch.setattr(ap, "run_agent_pipeline", lambda api_key, nse_symbol, data, progress_callback=None: local)
    progress = []
    got_data, got_result = app.run_analysis("SBIN", "sk", lambda value, label=None: progress.append((value, label)))
    assert got_data is data and got_result is local
    assert any(value == 20 for value, _ in progress)

    got_data, got_result = app.run_analysis("SBIN", "", None)
    assert got_result["mode"] == "local"

    monkeypatch.setattr(ap, "run_agent", lambda agent, prompt, deps: "SCORE: 8/10\nLooks good")
    ar = agent_or_fallback("Fundamentals", object(), "prompt", data, {})
    assert ar.source == "agent" and ar.score == 8
    monkeypatch.setattr(ap, "run_agent", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
    ar = agent_or_fallback("Fundamentals", object(), "prompt", data, {})
    assert ar.source == "local" and "agent failed" in ar.content


def test_web_price_source_helpers(monkeypatch):
    import services.market_data as md

    # Google Finance success, parse miss, out-of-range, and exception paths.
    html = '<div class="gO24Ff">SBIN</div></div><div class="LhDNu"><x jsname="Pdsbrc"><span>₹ 780.50</span>'
    monkeypatch.setattr(md, "_web_get_text", lambda url, **kw: html)
    assert md._price_from_google_finance("SBIN") == 780.50
    monkeypatch.setattr(md, "_web_get_text", lambda url, **kw: "no quote")
    assert md._price_from_google_finance("SBIN") is None
    monkeypatch.setattr(md, "_web_get_text", lambda url, **kw: (_ for _ in ()).throw(RuntimeError("net")))
    assert md._price_from_google_finance("SBIN") is None

    # NSE API success/miss/exception paths.
    calls = []
    def fake_web(url, **kw):
        calls.append(url)
        if "api/quote-equity" in url:
            return json.dumps({"priceInfo": {"lastPrice": "790.25"}})
        return "home"
    monkeypatch.setattr(md, "_web_get_text", fake_web)
    assert md._price_from_nse_quote_api("SBIN") == 790.25
    monkeypatch.setattr(md, "_web_get_text", lambda url, **kw: "{}")
    assert md._price_from_nse_quote_api("SBIN") is None

    # Current-source wrapper stops at first available source.
    monkeypatch.setattr(md, "_price_from_google_finance", lambda symbol: None)
    monkeypatch.setattr(md, "_price_from_nse_quote_api", lambda symbol: 123.0)
    assert md._current_price_from_web_sources("SBIN.NS") == 123.0
    assert md._current_price_from_web_search("SBIN.NS") == 123.0


def test_ddgs_snippet_price_paths(monkeypatch):
    import services.market_data as md

    class FakeDDGS:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def text(self, query, max_results=5):
            return [{"body": "SBIN share price is ₹ 801.35 today"}]

    mod = types.ModuleType("ddgs")
    mod.DDGS = FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", mod)
    assert md._price_from_ddgs_snippets("SBIN") == 801.35

    class BadDDGS(FakeDDGS):
        def text(self, *a, **k):
            raise RuntimeError("bad")
    mod.DDGS = BadDDGS
    assert md._price_from_ddgs_snippets("SBIN") is None


def test_sidebar_auth_and_research_render_branches(monkeypatch):
    import app

    # Non-interactive unauthenticated path.
    st = fake_st()
    monkeypatch.setattr(app, "st", st)
    monkeypatch.setattr(app, "is_authenticated", lambda: False)
    assert app.render_sidebar_access(interactive=False) == ""
    assert st.caption.called

    # Persisted auth restore path.
    st2 = fake_st()
    monkeypatch.setattr(app, "st", st2)
    monkeypatch.setattr(app, "is_authenticated", lambda: True)
    monkeypatch.setattr(app, "load_auth", lambda: "saved@example.com")
    monkeypatch.setattr(app, "get_user", lambda email: {"email": email, "plan": "free"})
    assert app.render_sidebar_access(interactive=False) == "saved@example.com"
    assert st2.success.called

    # Offline interactive path saves auth.
    st3 = fake_st()
    st3.text_input.return_value = "Dev@Example.com"
    monkeypatch.setattr(app, "st", st3)
    monkeypatch.setattr(app, "_supabase_offline", lambda: True)
    monkeypatch.setattr(app, "is_authenticated", lambda: False)
    saved = []
    monkeypatch.setattr(app, "save_auth", lambda email: saved.append(email))
    assert app.render_sidebar_access(interactive=True) == "dev@example.com"
    assert saved == ["dev@example.com"]

    # render_auth_gate already-authenticated path.
    st4 = fake_st()
    st4.session_state.user_email = "pro@example.com"
    monkeypatch.setattr(app, "st", st4)
    monkeypatch.setattr(app, "is_authenticated", lambda: True)
    monkeypatch.setattr("payment.get_user", lambda email: {"plan": "pro", "analyses_used": 2, "analyses_limit": 100})
    assert app.render_auth_gate() == "pro@example.com"

    # Research setup unauthenticated and authenticated quick-pick callback path.
    st5 = fake_st()
    st5.session_state.symbol_input = "TCS"
    monkeypatch.setattr(app, "st", st5)
    monkeypatch.setattr(app, "is_authenticated", lambda: False)
    assert app.render_research_setup() == "TCS"
    monkeypatch.setattr(app, "is_authenticated", lambda: True)
    st5.button.return_value = False
    st5.text_input.return_value = "RELIANCE"
    assert app.render_research_setup() == "TCS"


def test_signout_footer_and_report_error_branches(monkeypatch, tmp_path):
    import app

    st = fake_st()
    st.session_state.user_email = "u@example.com"
    st.session_state._session_report_count = 4
    monkeypatch.setattr(app, "st", st)
    user = types.SimpleNamespace(plan="free", analyses_limit=5)
    assert app.user_field({"x": 1}, "x", 0) == 1
    assert app.user_field(user, "plan", "x") == "free"
    monkeypatch.setattr(app, "get_user", lambda email: user)
    app.render_footer("u@example.com")
    assert st.markdown.called
    app.render_footer("")  # early return

    # _do_sign_out branches: no session and sign_out exception are both swallowed.
    st.session_state = SessionState({"user_email": "x", "_auth_verified": True, "_supabase_session": {}})
    monkeypatch.setattr(app, "clear_auth", lambda: None)
    client = MagicMock()
    client.auth.sign_out.side_effect = RuntimeError("ignore")
    monkeypatch.setattr(app, "get_supabase_client", lambda: client)
    app._do_sign_out()
    assert st.session_state["user_email"] == ""

    # JSON/report defensive branches.
    class BadItem:
        def item(self):
            raise RuntimeError("bad item")
    assert app.json_safe(BadItem()).startswith("<")
    assert app.restore_dataframe([{"index": "2026-01-01", "Close": 1}]).index[0].year == 2026
    data, result = app.restore_report_payload({"data": {}, "result": {"agent_outputs": {"x": object()}}})
    assert "x" in result["agent_outputs"]
    assert app.load_report("NOPE", "missing") is False
    assert app.report_payload_from_history({"symbol": "NOPE", "timestamp": "missing"}) is None

    class BadDir:
        def glob(self, pattern):
            raise RuntimeError("bad")
        def mkdir(self, *a, **k):
            raise RuntimeError("bad")
    monkeypatch.setattr(app, "REPORTS_DIR", BadDir())
    app.enforce_report_cap()
    assert app.save_report({}, {}) is None
    app.load_history_from_disk()


def test_run_analysis_error_branches(monkeypatch):
    import app
    import services.analysis_pipeline as ap

    monkeypatch.setattr(ap, "resolve_ticker", lambda symbol: {"symbol": ""})
    with pytest.raises(ValueError):
        app.run_analysis("unknown", "")

    monkeypatch.setattr(ap, "resolve_ticker", lambda symbol: {"symbol": "SBIN.NS"})
    monkeypatch.setattr(ap, "load_market_data", lambda symbol: (_ for _ in ()).throw(RuntimeError("data fail")))
    with pytest.raises(RuntimeError):
        app.run_analysis("SBIN", "")

    monkeypatch.setattr(ap, "load_market_data", lambda symbol: (_ for _ in ()).throw(ap.YFinanceRateLimitError("rate")))
    with pytest.raises(ap.YFinanceRateLimitError):
        app.run_analysis("SBIN", "")
