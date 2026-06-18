"""Coverage gap tests for app.py — pure/helper functions and render wrappers.

Targets: get_deepseek_key, _safe_ratio_name, _market_data_source_badge,
_synthetic_history, simple_markdown_to_html remaining branches, report_download_payload
fallback, signout helpers, render_scorecards/verdict/header wrappers, _deep_* helpers.
"""

import re
from unittest.mock import MagicMock, patch

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

def make_mock_st():
    st = MagicMock()
    st.session_state = SessionState()
    def columns(spec, *args, **kwargs):
        n = spec if isinstance(spec, int) else len(spec)
        return [Ctx() for _ in range(n)]
    st.columns.side_effect = columns
    st.expander.return_value = Ctx()
    st.container.return_value = Ctx()
    st.spinner.return_value = Ctx()
    st.sidebar = Ctx()
    return st


# ═══════════════════════════════════════════════════════════════════
# Pure helpers — no Streamlit needed
# ═══════════════════════════════════════════════════════════════════

class TestGetDeepseekKey:
    """get_deepseek_key — secrets, env fallback."""

    def test_from_secrets(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.secrets = {"DEEPSEEK_API_KEY": "sk-secret-key-123"}
        monkeypatch.setattr("app.st", mock_st)
        from app import get_deepseek_key
        assert get_deepseek_key() == "sk-secret-key-123"

    def test_from_env_when_secrets_empty(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.secrets = {"DEEPSEEK_API_KEY": ""}
        monkeypatch.setattr("app.st", mock_st)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key")
        from app import get_deepseek_key
        assert get_deepseek_key() == "sk-env-key"

    def test_from_env_when_secrets_missing_key(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.secrets = {}
        monkeypatch.setattr("app.st", mock_st)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-only")
        from app import get_deepseek_key
        assert get_deepseek_key() == "sk-env-only"

    def test_empty_when_both_missing(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.secrets = {}
        monkeypatch.setattr("app.st", mock_st)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        from app import get_deepseek_key
        assert get_deepseek_key() == ""

    def test_exception_accessing_secrets_falls_back_to_env(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.secrets.__getitem__.side_effect = KeyError("no key")
        monkeypatch.setattr("app.st", mock_st)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-fallback-env")
        from app import get_deepseek_key
        assert get_deepseek_key() == "sk-fallback-env"


class TestSafeRatioName:
    def test_valid_name(self):
        from app import _safe_ratio_name
        assert _safe_ratio_name("P/E Ratio") == "P/E Ratio"

    def test_none_name(self):
        from app import _safe_ratio_name
        assert _safe_ratio_name(None) == "Unknown"

    def test_empty_name(self):
        from app import _safe_ratio_name
        assert _safe_ratio_name("") == "Unknown"


class TestMarketDataSourceBadge:
    def test_screener_fallback(self):
        from app import _market_data_source_badge
        result = _market_data_source_badge({"source": "screener_fallback"})
        assert "Screener.in" in result
        assert "Yahoo Finance" in result

    def test_web_search_fallback(self):
        from app import _market_data_source_badge
        result = _market_data_source_badge({"source": "web_search_fallback"})
        assert "web fallback" in result.lower()
        assert "Screener.in" in result

    def test_default_yahoo(self):
        from app import _market_data_source_badge
        result = _market_data_source_badge({"source": "yfinance"})
        assert "Yahoo Finance" in result

    def test_unknown_source_defaults_to_yahoo(self):
        from app import _market_data_source_badge
        result = _market_data_source_badge({})
        assert "Yahoo Finance" in result


class TestSyntheticHistory:
    def test_creates_dataframe(self):
        from app import _synthetic_history
        import pandas as pd
        df = _synthetic_history(780.50)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1
        assert df["Close"].iloc[0] == 780.50
        assert "EMA20" in df.columns
        assert "RSI14" in df.columns
        assert df["RSI14"].iloc[0] == 50.0
        assert df["MACD"].iloc[0] == 0.0

    def test_pandas_not_available_returns_none(self, monkeypatch):
        # Simulate import failure
        import builtins
        original_import = builtins.__import__

        def fail_pandas(name, *args, **kwargs):
            if name == "pandas":
                raise ImportError("no pandas")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_pandas)
        from app import _synthetic_history
        result = _synthetic_history(100.0)
        assert result is None


class TestCleanEmail:
    def test_trim_and_lowercase(self):
        from app import _clean_email
        assert _clean_email("  Test@Example.COM  ") == "test@example.com"

    def test_none(self):
        from app import _clean_email
        assert _clean_email(None) == ""

    def test_empty(self):
        from app import _clean_email
        assert _clean_email("") == ""


# ═══════════════════════════════════════════════════════════════════
# simple_markdown_to_html — additional branches
# ═══════════════════════════════════════════════════════════════════

class TestSimpleMarkdownToHtmlBranches:
    def test_list_at_end_without_trailing_blank(self):
        """List at end of text — </ul> must still close."""
        from app import simple_markdown_to_html
        # No blank line after the list — the list-stack must close at EOF
        result = simple_markdown_to_html("Start\n- Item 1\n- Item 2")
        assert "<p>Start</p>" in result
        assert "<li>Item 1</li>" in result
        assert "<li>Item 2</li>" in result
        # Must close the ul
        assert result.count("</ul>") == 1
        # The last tag before end should be </ul>, not a <p>
        stripped = result.strip()
        assert stripped.endswith("</ul>") or "</ul>" in stripped

    def test_multiple_paragraphs_with_blanks(self):
        from app import simple_markdown_to_html
        result = simple_markdown_to_html("Para 1\n\n\n\nPara 4")
        assert "<p>Para 1</p>" in result
        assert "<p>Para 4</p>" in result
        # Blank lines are skipped correctly

    def test_single_line(self):
        from app import simple_markdown_to_html
        result = simple_markdown_to_html("Single line")
        assert result == "<p>Single line</p>"

    def test_bold_in_list_items(self):
        from app import simple_markdown_to_html
        result = simple_markdown_to_html("- **Bold item** description\n- Normal item")
        assert "<strong>Bold item</strong>" in result
        assert "<li>" in result

    def test_escapes_html_in_input(self):
        from app import simple_markdown_to_html
        result = simple_markdown_to_html("<script>xss</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


# ═══════════════════════════════════════════════════════════════════
# report_download_payload — text fallback
# ═══════════════════════════════════════════════════════════════════

class TestReportDownloadPayload:
    def make_data(self):
        return {
            "base_symbol": "SBIN", "symbol": "SBIN.NS",
            "name": "State Bank of India", "price": 780.50,
            "as_of": "16 Jun 2026", "exchange": "NSE",
            "fundamentals": {"trailing_pe": 12.5, "roe": 0.15, "debt_to_equity": 90,
                             "revenue_growth": 0.09},
            "technicals": {"trend": "Bullish", "rsi": 58, "macd": 3.2, "macd_signal": 2.1,
                           "ema20": 770, "ema50": 745, "support": 720, "resistance": 820,
                           "return_1y_pct": 18.5, "max_drawdown_pct": 22, "volatility_60d_pct": 28},
        }

    def make_result(self):
        from app import AgentResult
        outputs = {
            "Fundamentals": AgentResult(name="F", content="OK", score=7.5, source="agent"),
            "Technicals": AgentResult(name="T", content="OK", score=7.0, source="agent"),
            "Sentiment": AgentResult(name="S", content="OK", score=6.5, source="agent"),
            "Risk": AgentResult(name="R", content="OK", score=8.0, source="agent"),
        }
        return {
            "verdict": "BUY", "composite": 7.2, "generated_at": "16 Jun 2026",
            "final_report": "**BUY** SBIN with composite 7.2/10",
            "agent_outputs": outputs, "mode": "agent",
        }

    def test_pdf_path(self):
        from app import report_download_payload
        payload, filename, mime = report_download_payload(self.make_data(), self.make_result())
        assert isinstance(payload, bytes)
        assert "SBIN" in filename
        assert filename.endswith(".pdf")
        assert mime == "application/pdf"

    def test_fallback_txt_when_pdf_import_fails(self, monkeypatch):
        """When fpdf import fails, fall back to text."""
        import builtins
        original_import = builtins.__import__

        def fail_fpdf(name, *args, **kwargs):
            if name == "fpdf":
                raise ImportError("no fpdf")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_fpdf)
        # Need to reimport because app globals memoize fpdf
        import importlib
        import app
        importlib.reload(app)
        from app import report_download_payload
        payload, filename, mime = report_download_payload(self.make_data(), self.make_result())
        assert isinstance(payload, bytes)
        assert filename.endswith(".txt")
        assert mime == "text/plain"
        assert b"SBIN" in payload
        # Restore
        importlib.reload(app)

    def test_filename_no_base_symbol_uses_symbol(self):
        from app import report_download_payload
        data = self.make_data()
        del data["base_symbol"]
        payload, filename, mime = report_download_payload(data, self.make_result())
        assert "SBIN" in filename

    def test_filename_no_symbol_uses_default(self):
        from app import report_download_payload
        data = self.make_data()
        del data["base_symbol"]
        del data["symbol"]
        payload, filename, mime = report_download_payload(data, self.make_result())
        assert "stock_report" in filename


# ═══════════════════════════════════════════════════════════════════
# _deep_* helpers
# ═══════════════════════════════════════════════════════════════════

class TestDeepGetApiKey:
    def test_from_session_state_api_key(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.session_state = SessionState({"api_key": "sk-deep-key"})
        monkeypatch.setattr("app.st", mock_st)
        from app import _deep_get_api_key
        assert _deep_get_api_key() == "sk-deep-key"

    def test_from_session_state_deepseek_key(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.session_state = SessionState({"deepseek_api_key": "sk-ds-key"})
        monkeypatch.setattr("app.st", mock_st)
        from app import _deep_get_api_key
        assert _deep_get_api_key() == "sk-ds-key"

    def test_from_secrets_fallback(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.session_state = SessionState({})
        mock_st.secrets = {"DEEPSEEK_API_KEY": "sk-secret-deep"}
        monkeypatch.setattr("app.st", mock_st)
        from app import _deep_get_api_key
        assert _deep_get_api_key() == "sk-secret-deep"

    def test_empty_when_all_missing(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.session_state = SessionState({})
        mock_st.secrets = {}
        monkeypatch.setattr("app.st", mock_st)
        from app import _deep_get_api_key
        assert _deep_get_api_key() == ""


class TestDeepSymbol:
    def test_fallback_symbol(self):
        from app import _deep_symbol
        result = _deep_symbol({}, "SBIN")
        assert result == "SBIN.NS"

    def test_from_data_symbol(self):
        from app import _deep_symbol
        result = _deep_symbol({"symbol": "RELIANCE.NS"})
        assert result == "RELIANCE.NS"

    def test_from_data_nse_symbol(self):
        from app import _deep_symbol
        result = _deep_symbol({"nse_symbol": "TCS.NS"})
        assert result == "TCS.NS"

    def test_adds_ns_suffix(self):
        from app import _deep_symbol
        result = _deep_symbol({"ticker": "SBIN"})
        assert result == "SBIN.NS"

    def test_no_duplicate_ns(self):
        from app import _deep_symbol
        result = _deep_symbol({"symbol": "SBIN.NS"})
        assert result == "SBIN.NS"

    def test_empty_returns_empty(self):
        from app import _deep_symbol
        result = _deep_symbol({})
        assert result == ""

    def test_lowercase_uppercased(self):
        from app import _deep_symbol
        result = _deep_symbol({"symbol": "sbin.ns"})
        assert result == "SBIN.NS"


class TestDeepDataFrame:
    def test_non_empty_rows(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _deep_data_frame
        rows = [{"name": "A", "value": 100}, {"name": "B", "value": 200}]
        _deep_data_frame(rows)
        mock_st.dataframe.assert_called_once()
        mock_st.info.assert_not_called()

    def test_empty_rows_shows_info(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _deep_data_frame
        _deep_data_frame([])
        mock_st.info.assert_called_once()
        mock_st.dataframe.assert_not_called()


class TestDeepMetricRow:
    def test_with_items(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _deep_metric_row
        items = [("Price", 780.50), ("Volume", 12345)]
        _deep_metric_row(items)
        assert mock_st.metric.call_count == 2

    def test_none_value_shows_dash(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _deep_metric_row
        items = [("Price", None)]
        _deep_metric_row(items)
        mock_st.metric.assert_called_once()
        call_args = mock_st.metric.call_args
        assert call_args[0][1] == "—"

    def test_single_item(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _deep_metric_row
        _deep_metric_row([("Only", 42)])
        mock_st.metric.assert_called_once()


# ═══════════════════════════════════════════════════════════════════
# render wrappers — monkeypatched streamlit
# ═══════════════════════════════════════════════════════════════════

class TestRenderStockHeader:
    def test_calls_stock_header_card(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import render_stock_header
        data = {"symbol": "SBIN.NS", "name": "SBI"}
        called = []
        monkeypatch.setattr("app.stock_header_card", lambda d: called.append(d))
        render_stock_header(data)
        assert called == [data]


class TestRenderScorecards:
    def test_renders_4_scorecards(self, monkeypatch):
        mock_st = make_mock_st()
        mock_shadcn = MagicMock()
        monkeypatch.setattr("app.st", mock_st)
        score_card_mock = MagicMock()
        monkeypatch.setattr("app.score_card", score_card_mock)
        from app import render_scorecards, AgentResult
        outputs = {
            "Fundamentals": AgentResult("F", "OK", 7.5, "agent"),
            "Technicals": AgentResult("T", "OK", 6.5, "agent"),
            "Sentiment": AgentResult("S", "OK", 6.0, "agent"),
            "Risk": AgentResult("R", "OK", 8.0, "agent"),
        }
        render_scorecards(outputs)
        assert mock_st.columns.called
        assert score_card_mock.call_count == 4

    def test_missing_output_uses_default(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        score_card_mock = MagicMock()
        monkeypatch.setattr("app.score_card", score_card_mock)
        from app import render_scorecards, AgentResult
        outputs = {
            "Fundamentals": AgentResult("F", "OK", 7.5, "agent"),
        }
        render_scorecards(outputs)
        # Should still call caption 4 times (once per SCORE_ORDER dimension)
        assert score_card_mock.call_count == 4


class TestRenderVerdict:
    def test_renders_verdict_card(self, monkeypatch):
        mock_st = make_mock_st()
        mock_shadcn = MagicMock()
        monkeypatch.setattr("app.st", mock_st)
        monkeypatch.setattr("app.ui", mock_shadcn)
        verdict_badge_mock = MagicMock()
        status_pill_mock = MagicMock()
        monkeypatch.setattr("app.verdict_badge", verdict_badge_mock)
        monkeypatch.setattr("app.status_pill", status_pill_mock)
        from app import render_verdict
        result = {"composite": 7.2, "generated_at": "16 Jun 2026", "mode": "agent"}
        render_verdict(result)
        mock_shadcn.card.assert_called_once()
        assert verdict_badge_mock.called
        assert status_pill_mock.called


class TestRenderChart:
    def make_data(self, source="yfinance"):
        import pandas as pd
        import numpy as np
        dates = pd.date_range("2025-01-01", periods=30, freq="B")
        hist = pd.DataFrame({
            "Open": np.random.uniform(750, 800, 30),
            "High": np.random.uniform(780, 820, 30),
            "Low": np.random.uniform(740, 770, 30),
            "Close": np.random.uniform(760, 790, 30),
            "Volume": np.random.randint(1e6, 5e6, 30),
            "EMA20": np.random.uniform(760, 780, 30),
            "EMA50": np.random.uniform(740, 760, 30),
        }, index=dates)
        return {"history": hist, "source": source}

    def test_candlestick_with_ohlc(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import render_chart
        data = self.make_data("yfinance")
        render_chart(data)
        mock_st.plotly_chart.assert_called_once()

    def test_screener_fallback_shows_info(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import render_chart
        data = self.make_data("screener_fallback")
        render_chart(data)
        mock_st.info.assert_called_once()
        mock_st.plotly_chart.assert_not_called()

    def test_no_ohlc_uses_close_line(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import render_chart
        import pandas as pd
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        hist = pd.DataFrame({"Close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]}, index=dates)
        data = {"history": hist, "source": "yfinance"}
        render_chart(data)
        mock_st.plotly_chart.assert_called_once()


class TestRenderPeerComparison:
    def test_with_table(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_peer_comparison
        section = {"data": {"table": [{"name": "A", "pe": 10}]}}
        _render_peer_comparison(section)
        mock_st.dataframe.assert_called_once()

    def test_with_warnings(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_peer_comparison
        section = {"data": {}, "warnings": ["rate limited"]}
        _render_peer_comparison(section)
        mock_st.warning.assert_called_once()

    def test_with_valuation_flags(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_peer_comparison
        section = {"data": {"valuation_flags": [{"flag": "overvalued"}]}}
        _render_peer_comparison(section)
        assert mock_st.dataframe.call_count == 1


class TestRenderAnalystTargets:
    def test_renders_metrics(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_analyst_targets
        section = {"data": {"current_price": 780, "target_mean_price": 850,
                            "upside_downside_pct": "+8.9%", "number_of_analyst_opinions": 42}}
        _render_analyst_targets(section)
        assert mock_st.metric.call_count == 4
        mock_st.json.assert_called_once()


class TestRenderRiskFlags:
    def test_renders_metrics_and_table(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_risk_flags
        section = {"data": {"total_flags": 3, "total_checked": 20,
                            "flags": [{"description": "High debt"}]}}
        _render_risk_flags(section)
        assert mock_st.metric.call_count == 2
        mock_st.dataframe.assert_called_once()


class TestRenderValuation:
    def test_renders_valuation(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_valuation
        section = {"data": {"current_price": 780, "fair_value_range": {"base": 850},
                            "upside_pct": "+8.9%", "methods": [{"method": "DCF", "value": 880}]}}
        _render_valuation(section)
        assert mock_st.metric.call_count == 3
        assert mock_st.json.called or mock_st.markdown.called


class TestRenderGovernance:
    def test_renders_governance(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_governance
        section = {"data": {"governance_score": 7, "promoter_holding": 50, "pledged_pct": 0, "promoter_trend": "Stable", "flags": ["No major flags"]}}
        _render_governance(section)
        assert mock_st.metric.call_count == 4
        mock_st.warning.assert_called_once_with("No major flags")

    def test_with_warnings(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_governance
        section = {"data": {}, "warnings": ["governance data unavailable"]}
        _render_governance(section)
        mock_st.warning.assert_called_once()


class TestRenderThesis:
    def test_renders_thesis(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_thesis
        section = {"data": {"one_line_thesis": "BUY thesis here", "company_overview": "Overview", "bull_case": ["Bull"], "bear_case": ["Bear"], "key_catalysts": ["Catalyst"], "market_missing": "Missing"}}
        _render_thesis(section)
        mock_st.markdown.assert_called()

    def test_with_warnings(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_thesis
        section = {"data": {}, "warnings": ["thesis generation failed"]}
        _render_thesis(section)
        mock_st.warning.assert_called_once()


class TestRenderFinancialTrends:
    def test_with_figures(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        import plotly.graph_objects as go
        from app import _render_financial_trends
        fig = go.Figure(data=[go.Bar(x=[1, 2], y=[3, 4])])
        section = {"data": {"figures": {"Revenue": fig.to_dict()}}}
        _render_financial_trends(section)
        mock_st.plotly_chart.assert_called_once()

    def test_no_figures(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_financial_trends
        section = {"data": {"figures": {}}}
        _render_financial_trends(section)
        mock_st.info.assert_called_once()

    def test_with_summary(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_financial_trends
        section = {"data": {"figures": {}, "summary": [{"metric": "Revenue Growth", "value": "10%"}]}}
        _render_financial_trends(section)
        mock_st.dataframe.assert_called()


class TestRenderDeepPlaceholder:
    def test_renders_expanders(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_deep_placeholder
        _render_deep_placeholder()
        mock_st.info.assert_called_once()
        # Should create at least one expander
        assert mock_st.expander.called


class TestRenderEnhancedPdf:
    def test_renders_download_button(self, monkeypatch):
        mock_st = make_mock_st()
        monkeypatch.setattr("app.st", mock_st)
        from app import _render_enhanced_pdf
        data = {"symbol": "SBIN.NS", "name": "SBI"}
        quick_result = {"verdict": "BUY"}
        deep_result = {"generated_at": "2026-06-16"}
        _render_enhanced_pdf(data, quick_result, deep_result, "SBIN.NS")
        # Should call st.download_button
        assert mock_st.download_button.called or mock_st.button.called


# ═══════════════════════════════════════════════════════════════════
# sign-out helpers
# ═══════════════════════════════════════════════════════════════════

class TestDoSignOut:
    def test_clears_session_and_calls_clear_auth(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.session_state = SessionState({
            "user_email": "test@test.com",
            "_auth_verified": True,
            "_supabase_session": {},
            "_otp_sent": True,
            "_otp_email": "test@test.com",
            "_email_input": "test@test.com",
            "_otp_input": "123456",
        })
        monkeypatch.setattr("app.st", mock_st)

        mock_clear_auth = MagicMock()
        monkeypatch.setattr("app.clear_auth", mock_clear_auth)

        mock_get_client = MagicMock(return_value=None)  # no supabase client
        monkeypatch.setattr("app.get_supabase_client", mock_get_client)

        from app import _do_sign_out
        _do_sign_out()

        assert mock_st.session_state["user_email"] == ""
        assert "_auth_verified" not in mock_st.session_state
        mock_clear_auth.assert_called_once()

    def test_calls_supabase_sign_out_when_client_available(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.session_state = SessionState({
            "user_email": "test@test.com",
            "_auth_verified": True,
            "_supabase_session": {},
            "_otp_sent": True,
            "_otp_email": "test@test.com",
            "_email_input": "test@test.com",
            "_otp_input": "123456",
        })
        monkeypatch.setattr("app.st", mock_st)

        mock_clear_auth = MagicMock()
        monkeypatch.setattr("app.clear_auth", mock_clear_auth)

        mock_client = MagicMock()
        mock_get_client = MagicMock(return_value=mock_client)
        monkeypatch.setattr("app.get_supabase_client", mock_get_client)

        from app import _do_sign_out
        _do_sign_out()

        mock_client.auth.sign_out.assert_called_once()

    def test_supabase_sign_out_exception_is_swallowed(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.session_state = SessionState({
            "user_email": "test@test.com",
            "_auth_verified": True,
            "_supabase_session": {},
            "_otp_sent": True,
            "_otp_email": "test@test.com",
            "_email_input": "test@test.com",
            "_otp_input": "123456",
        })
        monkeypatch.setattr("app.st", mock_st)

        mock_clear_auth = MagicMock()
        monkeypatch.setattr("app.clear_auth", mock_clear_auth)

        mock_client = MagicMock()
        mock_client.auth.sign_out.side_effect = RuntimeError("network error")
        mock_get_client = MagicMock(return_value=mock_client)
        monkeypatch.setattr("app.get_supabase_client", mock_get_client)

        from app import _do_sign_out
        _do_sign_out()  # should not raise

        mock_clear_auth.assert_called_once()
        mock_client.auth.sign_out.assert_called_once()


class TestRenderSidebarSignOut:
    def test_early_return_when_not_authenticated(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.session_state = SessionState({"user_email": ""})
        monkeypatch.setattr("app.st", mock_st)
        monkeypatch.setattr("app.is_authenticated", lambda: False)

        from app import render_sidebar_sign_out
        render_sidebar_sign_out()
        # Should not render button
        mock_st.button.assert_not_called()


class TestRenderMainSignOut:
    def test_early_return_when_not_authenticated(self, monkeypatch):
        mock_st = make_mock_st()
        mock_st.session_state = SessionState({"user_email": ""})
        monkeypatch.setattr("app.st", mock_st)
        monkeypatch.setattr("app.is_authenticated", lambda: False)

        from app import render_main_sign_out
        render_main_sign_out()
        mock_st.button.assert_not_called()
