"""Coverage gap tests for ui.py — all non-network helpers and render wrappers.

Uses monkeypatched streamlit.markdown / streamlit_shadcn_ui wrappers.
"""

from unittest.mock import MagicMock

# ═══════════════════════════════════════════════════════════════════
# ui.py helpers
# ═══════════════════════════════════════════════════════════════════


class TestSafe:
    def test_safe_escapes_html(self):
        from ui import _safe

        assert "&lt;script&gt;" in _safe("<script>alert(1)</script>")
        assert "&quot;" in _safe('"hello"')

    def test_safe_none(self):
        from ui import _safe

        assert _safe(None) == ""

    def test_safe_empty(self):
        from ui import _safe

        assert _safe("") == ""

    def test_safe_zero(self):
        from ui import _safe

        assert _safe(0) == ""


class TestScoreTone:
    def test_healthy(self):
        from ui import _score_tone

        variant, color, state = _score_tone(8.0, 10.0)
        assert variant == "default"
        assert color == "#22c55e"
        assert state == "Healthy"

    def test_healthy_at_boundary(self):
        from ui import _score_tone

        variant, color, state = _score_tone(7.0, 10.0)
        assert state == "Healthy"

    def test_watch(self):
        from ui import _score_tone

        variant, color, state = _score_tone(5.5, 10.0)
        assert variant == "secondary"
        assert color == "#f59e0b"
        assert state == "Watch"

    def test_watch_at_boundary(self):
        from ui import _score_tone

        variant, color, state = _score_tone(5.0, 10.0)
        assert state == "Watch"

    def test_weak(self):
        from ui import _score_tone

        variant, color, state = _score_tone(3.0, 10.0)
        assert variant == "destructive"
        assert color == "#ef4444"
        assert state == "Weak"

    def test_zero_max_score(self):
        from ui import _score_tone

        variant, color, state = _score_tone(5.0, 0)
        assert state == "Weak"  # ratio = 0


# ═══════════════════════════════════════════════════════════════════
# ui.py render functions — monkeypatched streamlit
# ═══════════════════════════════════════════════════════════════════


class TestPageHeader:
    def test_calls_st_markdown(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import page_header

        page_header("Title", "Subtitle text")
        mock_st.markdown.assert_called_once()
        html = mock_st.markdown.call_args[0][0]
        assert "Title" in html
        # Product title and subtitle are used in the masthead and hero, escaped.
        assert "Subtitle text" in html
        assert mock_st.markdown.call_args[1]["unsafe_allow_html"] is True


class TestSampleReportPreview:
    def test_default_symbol_infy(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import sample_report_preview

        sample_report_preview("")
        html = mock_st.markdown.call_args[0][0]
        assert "INFY" in html
        assert "Infosys" in html

    def test_sbin_symbol(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import sample_report_preview

        sample_report_preview("SBIN")
        html = mock_st.markdown.call_args[0][0]
        assert "SBIN" in html
        assert "State Bank of India" in html
        assert "Strong deposit franchise" in html

    def test_reliance(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import sample_report_preview

        sample_report_preview("RELIANCE")
        html = mock_st.markdown.call_args[0][0]
        assert "integrated operations" in html.lower() or "RELIANCE" in html

    def test_tcs(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import sample_report_preview

        sample_report_preview("TCS")
        html = mock_st.markdown.call_args[0][0]
        assert "TCS" in html

    def test_unknown_ticker_uses_default(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import sample_report_preview

        sample_report_preview("UNKNOWN")
        html = mock_st.markdown.call_args[0][0]
        assert "UNKNOWN" in html
        assert "BUY" in html


class TestExecutiveVerdictStrip:
    def test_renders_verdict(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import executive_verdict_strip

        data = {"base_symbol": "RELIANCE", "symbol": "RELIANCE.NS"}
        result = {
            "composite": 7.5,
            "verdict": "BUY",
            "mode": "agent",
            "generated_at": "16 Jun 2026",
        }
        executive_verdict_strip(data, result)
        mock_st.markdown.assert_called_once()
        html = mock_st.markdown.call_args[0][0]
        assert "BUY" in html
        assert "RELIANCE" in html
        assert "7.5/10" in html
        assert "75%" in html

    def test_uses_data_symbol_fallback(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import executive_verdict_strip

        data = {"symbol": "TCS.NS"}
        result = {
            "composite": 5.0,
            "verdict": "HOLD",
            "mode": "local",
            "generated_at": "",
        }
        executive_verdict_strip(data, result)
        html = mock_st.markdown.call_args[0][0]
        assert "TCS.NS" in html

    def test_missing_verdict_name_defaults(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import executive_verdict_strip

        data: dict = {}
        result: dict = {}
        executive_verdict_strip(data, result)
        html = mock_st.markdown.call_args[0][0]
        assert "Unavailable" in html


class TestKpiCard:
    def test_calls_shadcn_metric_card(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import kpi_card

        kpi_card("P/E", "12.5", "Trailing", "📈")
        mock_shadcn.metric_card.assert_called_once()
        kwargs = mock_shadcn.metric_card.call_args[1]
        assert kwargs["title"] == "📈 P/E"
        assert kwargs["content"] == "12.5"
        assert kwargs["description"] == "Trailing"

    def test_no_icon(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import kpi_card

        kpi_card("Market Cap", "₹6,500 Cr")
        mock_shadcn.metric_card.assert_called_once()
        kwargs = mock_shadcn.metric_card.call_args[1]
        assert kwargs["title"] == "Market Cap"


class TestScoreCard:
    def test_calls_shadcn_card_and_badges(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import score_card

        score_card("Fundamentals", 7.8, 10.0)
        assert mock_shadcn.card.called
        assert mock_shadcn.badges.called
        mock_st.markdown.assert_called_once()

    def test_score_bar_width(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import score_card

        score_card("Test", 5.0, 10.0)
        html = mock_st.markdown.call_args[0][0]
        assert "width:50%" in html


class TestVerdictBadge:
    def test_strong_buy(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import verdict_badge

        verdict_badge("STRONG BUY")
        mock_shadcn.badges.assert_called_once()
        badges = mock_shadcn.badges.call_args[0][0]
        assert badges[0][0] == "STRONG BUY"
        assert badges[0][1] == "default"

    def test_buy(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import verdict_badge

        verdict_badge("BUY")
        badges = mock_shadcn.badges.call_args[0][0]
        assert badges[0][1] == "default"

    def test_hold(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import verdict_badge

        verdict_badge("HOLD")
        badges = mock_shadcn.badges.call_args[0][0]
        assert badges[0][1] == "secondary"

    def test_sell(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import verdict_badge

        verdict_badge("SELL")
        badges = mock_shadcn.badges.call_args[0][0]
        assert badges[0][1] == "destructive"

    def test_avoid(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import verdict_badge

        verdict_badge("AVOID")
        badges = mock_shadcn.badges.call_args[0][0]
        assert badges[0][1] == "destructive"

    def test_unknown_verdict(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import verdict_badge

        verdict_badge("weird status")
        badges = mock_shadcn.badges.call_args[0][0]
        assert badges[0][1] == "outline"


class TestStockHeaderCard:
    def test_positive_change(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import stock_header_card

        data = {
            "exchange": "NSE",
            "symbol": "SBIN.NS",
            "base_symbol": "SBIN",
            "name": "State Bank of India",
            "price": 780.50,
            "change": 12.30,
            "change_pct": 1.60,
            "as_of": "16 Jun 2026",
        }
        stock_header_card(data)
        mock_st.markdown.assert_called_once()
        html = mock_st.markdown.call_args[0][0]
        assert "positive" in html
        assert "+12.30" in html
        assert "SBIN" in html

    def test_negative_change(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import stock_header_card

        data = {
            "symbol": "TCS.NS",
            "base_symbol": "TCS",
            "name": "TCS",
            "price": 3500.00,
            "change": -50.00,
            "change_pct": -1.41,
            "exchange": "NSE",
            "as_of": "16 Jun 2026",
        }
        stock_header_card(data)
        html = mock_st.markdown.call_args[0][0]
        assert "negative" in html
        assert "-50.00" in html

    def test_zero_change(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import stock_header_card

        data = {
            "symbol": "TEST.NS",
            "base_symbol": "TEST",
            "name": "Test",
            "price": 100.00,
            "change": 0.0,
            "change_pct": 0.0,
            "exchange": "NSE",
            "as_of": "16 Jun 2026",
        }
        stock_header_card(data)
        html = mock_st.markdown.call_args[0][0]
        assert "positive" in html  # 0 is >= 0


class TestInfoAlert:
    def test_info_type(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import info_alert

        info_alert("Something happened", "info")
        mock_shadcn.alert.assert_called_once()
        kwargs = mock_shadcn.alert.call_args[1]
        assert "blue" in kwargs["class_name"]

    def test_warning_type(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import info_alert

        info_alert("Warning!", "warning")
        kwargs = mock_shadcn.alert.call_args[1]
        assert "amber" in kwargs["class_name"]

    def test_error_type(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import info_alert

        info_alert("Error!", "error")
        kwargs = mock_shadcn.alert.call_args[1]
        assert "red" in kwargs["class_name"]

    def test_success_type(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import info_alert

        info_alert("Success!", "success")
        kwargs = mock_shadcn.alert.call_args[1]
        assert "emerald" in kwargs["class_name"]

    def test_unknown_type_defaults(self, monkeypatch):
        mock_shadcn = MagicMock()
        monkeypatch.setattr("ui.shadcn", mock_shadcn)
        from ui import info_alert

        info_alert("Bogus", "bogus")
        kwargs = mock_shadcn.alert.call_args[1]
        assert "slate" in kwargs["class_name"]


class TestSectionTitle:
    def test_renders_html(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import section_title

        section_title("My Section")
        mock_st.markdown.assert_called_once()
        html = mock_st.markdown.call_args[0][0]
        assert "My Section" in html
        assert "section-title" in html


class TestEmptyState:
    def test_without_steps(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import empty_state

        empty_state("Welcome", "Please enter a ticker")
        mock_st.markdown.assert_called_once()
        html = mock_st.markdown.call_args[0][0]
        assert "Welcome" in html
        assert "Please enter a ticker" in html
        assert "<ol>" not in html

    def test_with_steps(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import empty_state

        empty_state("How to use", "Follow these steps", ["Step 1", "Step 2", "Step 3"])
        mock_st.markdown.assert_called_once()
        html = mock_st.markdown.call_args[0][0]
        assert "<ol>" in html
        assert "<li>" in html
        assert "Step 1" in html
        assert "Step 3" in html


class TestStatusPill:
    def test_renders_html(self, monkeypatch):
        mock_st = MagicMock()
        monkeypatch.setattr("ui.st", mock_st)
        from ui import status_pill

        status_pill("Mode", "agent")
        mock_st.markdown.assert_called_once()
        html = mock_st.markdown.call_args[0][0]
        assert "Mode" in html
        assert "agent" in html
        assert "status-pill" in html
