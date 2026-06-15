"""Enhanced fpdf2 report generation for Deep Research.

Produces an institutional-style equity research PDF: cover page with verdict
panel, executive investment view, business-model map, forecast snapshot,
quality-of-earnings lenses, valuation scenarios, risk dashboard, catalyst
calendar, governance, and disclaimer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fpdf import FPDF, XPos, YPos


# ---------------------------------------------------------------------------
# Palette and layout constants (Ali Abdaal light / institutional)
# ---------------------------------------------------------------------------
C_BG = (255, 255, 255)
C_TEXT = (26, 26, 26)
C_HEADER = (15, 23, 42)
C_PANEL = (245, 245, 245)
C_BORDER = (232, 232, 232)
C_ACCENT = (29, 185, 84)
C_GRAY = (107, 114, 128)

PAGE_W = 210
PAGE_H = 297
MARGIN = 16


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def _safe_text(value: Any, max_len: int | None = None) -> str:
    text = "" if value is None else str(value)
    replacements = {
        "₹": "Rs.",
        "—": "-",
        "–": "-",
        "’": "'",
        "“": '"',
        "”": '"',
        "×": "x",
        "•": "-",
        "≈": "~",
        "≤": "<=",
        "≥": ">=",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.encode("latin-1", "replace").decode("latin-1")
    if max_len and len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


def _fmt(value: Any, unit: str = "") -> str:
    if value is None or value == "":
        return "-"
    try:
        num = float(str(value).replace(",", "").replace("%", "").replace("Rs.", "").replace("Cr", "").strip())
    except Exception:
        return _safe_text(str(value))
    if abs(num) >= 1_000_000_000:
        return f"{unit}{num / 1_000_000_000:.2f}B"
    if abs(num) >= 1_000_000:
        return f"{unit}{num / 1_000_000:.2f}M"
    if abs(num) >= 1_000 and isinstance(value, (int, float)):
        return f"{unit}{num:,.0f}"
    if "." in str(value):
        return f"{unit}{num:.2f}"
    return f"{unit}{num:.1f}" if abs(num) < 100 else f"{unit}{num:,.0f}"


def _pct(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        num = float(str(value).replace("%", "").strip())
    except Exception:
        return _safe_text(str(value))
    return f"{num:.1f}%"


def _unwrap(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return data.get("data") if isinstance(data.get("data"), dict) else data


def _lines_from_list(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    return [_safe_text(item) for item in items if item]


# ---------------------------------------------------------------------------
# Fallback
# ---------------------------------------------------------------------------
def _fallback_text_report(
    data: dict[str, Any],
    quick_result: dict[str, Any],
    deep_result: dict[str, Any],
    reason: str,
) -> bytes:
    symbol = data.get("symbol") or data.get("nse_symbol") or deep_result.get("symbol") or "Stock"
    thesis = _unwrap(deep_result.get("thesis"))
    valuation = _unwrap(deep_result.get("valuation"))
    risk = _unwrap(deep_result.get("risk_flags"))
    lines = [
        f"Stock Research Report - {symbol}",
        "=" * 72,
        f"PDF generation fallback reason: {reason}",
        "",
        "Executive Summary",
        _safe_text(thesis.get("one_line_thesis") or "Unavailable"),
        "",
        "Quick Result",
        _safe_text(quick_result),
        "",
        "Valuation",
        _safe_text(valuation),
        "",
        "Risk Flags",
        _safe_text(risk),
        "",
        "Disclaimer",
        "This report is for research workflow support only and is not investment advice.",
    ]
    return "\n".join(lines).encode("utf-8")


# ---------------------------------------------------------------------------
# PDF primitives
# ---------------------------------------------------------------------------
def _set_color(pdf: Any, rgb: tuple[int, int, int]) -> None:
    pdf.set_text_color(*rgb)


def _section_header(pdf: Any, title: str) -> None:
    pdf.set_font("Helvetica", "B", 14)
    _set_color(pdf, C_HEADER)
    pdf.cell(0, 8, _safe_text(title), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*C_ACCENT)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)


def _para(pdf: Any, text: Any, size: int = 10, bold: bool = False) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "B" if bold else "", size)
    _set_color(pdf, C_TEXT)
    pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 5.5, _safe_text(text, 1800))
    pdf.ln(1)


def _bullets(pdf: Any, items: list[str], size: int = 10) -> None:
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Helvetica", "", size)
    _set_color(pdf, C_TEXT)
    for item in items:
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 5.3, f"- {_safe_text(item, 500)}")
    pdf.ln(1)


def _render_table(
    pdf: Any,
    headers: list[str],
    rows: list[list[Any]],
    col_widths: list[float] | None = None,
    align: list[str] | None = None,
) -> None:
    """Render a professional table with header row and alternating fills."""
    usable_width = pdf.w - pdf.l_margin - pdf.r_margin
    if col_widths is None:
        col_widths = [usable_width / len(headers)] * len(headers)
    if align is None:
        align = ["L"] * len(headers)

    header_height = 7
    row_height = 7.5

    # Header
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(*C_HEADER)
    pdf.set_text_color(255, 255, 255)
    pdf.set_draw_color(*C_BORDER)
    for header, width in zip(headers, col_widths):
        pdf.cell(width, header_height, _safe_text(header, 24), border=1, align="C", fill=True)
    pdf.ln()

    # Rows
    pdf.set_font("Helvetica", "", 9)
    _set_color(pdf, C_TEXT)
    for index, row in enumerate(rows):
        fill = index % 2 == 1
        if fill:
            pdf.set_fill_color(*C_PANEL)
        for value, width, col_align in zip(row, col_widths, align):
            text = _safe_text(value, 60) if value is not None else "-"
            pdf.cell(width, row_height, text, border=1, align=col_align, fill=fill)
        pdf.ln()
    pdf.ln(2)


def _kpi_box(pdf: Any, label: str, value: str, subtext: str = "") -> None:
    x = pdf.get_x()
    y = pdf.get_y()
    box_w = 40
    box_h = 16
    pdf.set_fill_color(*C_PANEL)
    pdf.set_draw_color(*C_BORDER)
    pdf.rect(x, y, box_w, box_h, style="FD")
    pdf.set_xy(x + 2, y + 1.5)
    pdf.set_font("Helvetica", "", 6.5)
    _set_color(pdf, C_GRAY)
    pdf.cell(box_w - 4, 4, _safe_text(label, 24), new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(x + 2, y + 6)
    pdf.set_font("Helvetica", "B", 10)
    _set_color(pdf, C_TEXT)
    pdf.cell(box_w - 4, 6, _safe_text(value, 14), new_x="LMARGIN", new_y="NEXT")
    if subtext:
        pdf.set_xy(x + 2, y + 12)
        pdf.set_font("Helvetica", "", 6)
        _set_color(pdf, C_GRAY)
        pdf.cell(box_w - 4, 4, _safe_text(subtext, 26), new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(x + box_w + 2, y)


def _footer(pdf: Any) -> None:
    pdf.set_y(-12)
    pdf.set_font("Helvetica", "", 8)
    _set_color(pdf, C_GRAY)
    pdf.cell(0, 5, f"Page {pdf.page_no()}", align="R")


# ---------------------------------------------------------------------------
# Data extractors
# ---------------------------------------------------------------------------
def _extract_financial_summary(fin: dict[str, Any]) -> tuple[list[str], list[list[str]]]:
    data = _unwrap(fin)
    pl = data.get("profit_loss", {})
    years = data.get("years", [])
    sales = pl.get("sales") or []
    op = pl.get("operating_profit") or []
    opm = pl.get("opm_pct") or []
    npm = pl.get("npm_pct") or []
    pat = pl.get("net_profit") or []
    eps = pl.get("eps") or []
    ratios = data.get("ratio_series", {})
    roe = ratios.get("roe_pct") or []
    roce = ratios.get("roce_pct") or []
    de = ratios.get("debt_to_equity") or []

    length = max(len(sales), len(op), len(opm), len(pat), len(eps), len(roe), len(roce), len(de), 1)
    if not years or len(years) != length:
        years = [f"Y-{length - i}" for i in range(length)]

    headers = ["Metric"] + [_safe_text(y, 10) for y in years]
    rows: list[list[str]] = []

    def add_row(label: str, series: list[Any], formatter: Any = _fmt) -> None:
        if not series:
            return
        padded = [None] * (length - len(series)) + list(series)
        rows.append([label] + [formatter(v) for v in padded])

    add_row("Revenue (Rs. Cr)", sales)
    add_row("EBITDA/OP (Rs. Cr)", op)
    add_row("OPM %", opm, _pct)
    add_row("Net Profit (Rs. Cr)", pat)
    add_row("EPS (Rs.)", eps)
    add_row("ROE %", roe, _pct)
    add_row("ROCE %", roce, _pct)
    add_row("Debt / Equity", de)
    return headers, rows


def _build_scenarios(valuation: dict[str, Any]) -> list[list[str]]:
    fair = valuation.get("fair_value_range") or {}
    base_value = fair.get("base")
    low_value = fair.get("low")
    high_value = fair.get("high")
    base = _fmt(base_value, "Rs. ")
    low = _fmt(low_value, "Rs. ")
    high = _fmt(high_value, "Rs. ")
    return [
        ["Bear", "25%", "Slower growth / higher risk", low, "Margin compression or capital misallocation"],
        ["Base", "50%", "Balanced growth and margin", base, "Current trajectory and reasonable multiples"],
        ["Bull", "25%", "Acceleration / multiple expansion", high, "Execution beats and re-rating catalysts"],
    ]


def _build_valuation_methods(valuation: dict[str, Any]) -> list[list[str]]:
    methods = valuation.get("methods") or []
    if not methods:
        return []
    rows = []
    for method in methods:
        weight = method.get("weight")
        rows.append([
            method.get("method", "-"),
            f"{float(weight) * 100:.0f}%" if weight is not None else "-",
            _safe_text(method.get("assumption"), 90),
            _fmt(method.get("fair_value"), "Rs. "),
        ])
    return rows


def _quality_lenses(flags: list[dict[str, Any]]) -> list[list[str]]:
    triggered_names = {f.get("name", "") for f in flags if f.get("triggered")}
    return [
        ["Revenue recognition", "Sales growth consistent with volume", "Q-o-Q volatility", "Declining sales 3Q+"],
        ["Working capital", "Receivables in line with sales", "Receivables rising faster", "Aggressive credit terms"],
        ["Cash conversion", "OCF tracks PAT", "OCF lags PAT", "Negative OCF with PAT"],
        ["Leverage", "D/E stable vs peers", "D/E above peer median", "Interest coverage < 1.5x"],
        ["Governance", "Stable promoter holding", "Promoter selling", "Pledge > 25% / auditor changes"],
    ]


# ---------------------------------------------------------------------------
# Main PDF builder
# ---------------------------------------------------------------------------
def build_enhanced_pdf(
    data: dict[str, Any],
    quick_result: dict[str, Any],
    deep_result: dict[str, Any],
) -> bytes:
    """Build a multi-page institutional-style fpdf2 report."""
    try:
        symbol = data.get("symbol") or data.get("nse_symbol") or deep_result.get("symbol") or "Stock"
        company = data.get("company") or data.get("name") or symbol
        base_symbol = data.get("base_symbol") or symbol.split(".")[0]
        verdict = quick_result.get("verdict") or quick_result.get("final_verdict") or "Unavailable"
        score = quick_result.get("score") or quick_result.get("composite_score") or quick_result.get("final_score")
        score_label = _safe_text(score) if score is not None else "-"

        thesis = _unwrap(deep_result.get("thesis"))
        peers = _unwrap(deep_result.get("peer_comparison"))
        analyst = _unwrap(deep_result.get("analyst_targets"))
        fin = _unwrap(deep_result.get("financials") or {})
        trends = _unwrap(deep_result.get("financial_trends"))
        risks = _unwrap(deep_result.get("risk_flags"))
        valuation = _unwrap(deep_result.get("valuation"))
        governance = _unwrap(deep_result.get("governance"))

        current_price = valuation.get("current_price") or analyst.get("current_price") or data.get("price") or data.get("current_price")
        fair = valuation.get("fair_value_range") or {}
        upside = valuation.get("upside_pct")
        target = fair.get("base") or analyst.get("target_mean_price")

        risk_count = risks.get("total_flags") or 0
        risk_rating = "Low" if risk_count == 0 else "Moderate" if risk_count <= 2 else "High"

        today = datetime.now().strftime("%d %b %Y")

        # Create PDF subclass for footer
        class ReportPDF(FPDF):
            def footer(self) -> None:
                _footer(self)

        pdf = ReportPDF()
        pdf.set_auto_page_break(auto=True, margin=14)
        pdf.set_margins(MARGIN, MARGIN, MARGIN)

        # ---------------- Cover page ----------------
        pdf.add_page()
        pdf.set_fill_color(*C_BG)
        pdf.rect(0, 0, PAGE_W, PAGE_H, "F")

        # Brand bar placeholder
        pdf.set_fill_color(*C_HEADER)
        pdf.rect(0, 0, PAGE_W, 22, "F")
        pdf.set_xy(MARGIN, 6)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 10, "EQUITY RESEARCH REPORT", ln=1)

        # Title block
        pdf.set_y(36)
        pdf.set_font("Helvetica", "B", 22)
        _set_color(pdf, C_HEADER)
        pdf.multi_cell(PAGE_W - MARGIN * 2, 10, _safe_text(str(company), 60), align="L")

        pdf.set_font("Helvetica", "", 10)
        _set_color(pdf, C_GRAY)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(PAGE_W - MARGIN * 2, 5.5, f"Ticker: {_safe_text(base_symbol, 25)}   |   Exchange: NSE   |   Date: {today}", align="L")
        pdf.ln(2)

        # Verdict panel
        panel_h = 30
        panel_y = pdf.get_y()
        panel_w = PAGE_W - MARGIN * 2
        pdf.set_fill_color(*C_PANEL)
        pdf.set_draw_color(*C_BORDER)
        pdf.rect(MARGIN, panel_y, panel_w, panel_h, style="FD")

        # Verdict column
        verdict_w = 34
        pdf.set_xy(MARGIN + 4, panel_y + 5)
        pdf.set_font("Helvetica", "B", 8)
        _set_color(pdf, C_GRAY)
        pdf.cell(verdict_w, 5, "VERDICT", new_x="LMARGIN", new_y="NEXT")
        pdf.set_xy(MARGIN + 4, panel_y + 12)
        pdf.set_font("Helvetica", "B", 18)
        _set_color(pdf, C_ACCENT)
        pdf.cell(verdict_w, 9, _safe_text(str(verdict).upper(), 8), new_x="LMARGIN", new_y="NEXT")

        # KPI boxes inside panel
        pdf.set_xy(MARGIN + verdict_w + 6, panel_y + 6)
        _kpi_box(pdf, "Target Price", _fmt(target, "Rs. "), "Base case")
        _kpi_box(pdf, "Upside", _fmt(upside) if upside is not None else "-", "% vs current")
        _kpi_box(pdf, "Score", score_label, "Out of 10")

        pdf.set_y(panel_y + panel_h + 6)
        pdf.set_font("Helvetica", "B", 10)
        _set_color(pdf, C_HEADER)
        pdf.cell(0, 6, "Investment Thesis", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        _set_color(pdf, C_TEXT)
        pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin, 5.5, _safe_text(thesis.get("one_line_thesis") or "Investment thesis unavailable.", 1000))

        pdf.ln(4)
        pdf.set_draw_color(*C_BORDER)
        pdf.line(MARGIN, pdf.get_y(), PAGE_W - MARGIN, pdf.get_y())
        pdf.ln(3)
        pdf.set_font("Helvetica", "", 8)
        _set_color(pdf, C_GRAY)
        pdf.multi_cell(
            pdf.w - pdf.l_margin - pdf.r_margin,
            4.5,
            "Important notice: This report is an illustrative research aid generated from structured data and models. "
            "It is not investment advice, a recommendation, or a substitute for audited financial statements, SEBI-registered research, or professional diligence.",
        )

        # ---------------- Executive Investment View ----------------
        pdf.add_page()
        _section_header(pdf, "Executive Investment View")
        _para(pdf, thesis.get("one_line_thesis") or "Investment thesis unavailable.", bold=True)
        _para(pdf, thesis.get("company_overview") or "Company overview unavailable.")

        pdf.ln(2)
        _para(pdf, "Key Investment Arguments", bold=True, size=11)
        _bullets(pdf, _lines_from_list(thesis.get("bull_case"))[:5])

        _para(pdf, "Decision Grid", bold=True, size=11)
        decision_rows = [
            ["Is the market opportunity large enough?", "Review business-model map", "Sector size, TAM, and growth drivers"],
            ["Is the moat defensible?", "Assess returns and margin stability", "ROE/ROCE, OPM trend, peer comparison"],
            ["Is the valuation supportable?", "Check fair-value range and methods", "Multiples, DCF assumptions, upside %"],
            ["What can break the thesis?", "Monitor risk flags and catalysts", "Leverage, governance, earnings quality"],
        ]
        _render_table(
            pdf,
            ["Question", "Base Answer", "Evidence Needed"],
            decision_rows,
            col_widths=[70, 55, 53],
        )

        # ---------------- Company and Market Architecture ----------------
        pdf.add_page()
        _section_header(pdf, "Company and Market Architecture")
        _para(pdf, "Business Model Map", bold=True, size=11)
        business_rows = [
            ["Core product / service", "Volume x price / fee", "Repeat usage, low churn", "Pricing power and competition"],
            ["Revenue mix", "Segment contribution", "Diversified, growing segments", "Concentration risk"],
            ["Cost structure", "Fixed vs variable leverage", "Operating leverage improving", "Input / funding-cost pressure"],
            ["Capital allocation", "ROCE and reinvestment rate", "ROCE > WACC", "Low-return expansion or M&A"],
        ]
        _render_table(
            pdf,
            ["Revenue Stream", "Economic Driver", "Quality Marker", "Diligence Concern"],
            business_rows,
            col_widths=[40, 48, 48, 42],
        )
        _para(pdf, "Interpretation: A durable investment case requires evidence of reinvestment at returns above the cost of capital, coupled with pricing power or switching costs that protect margins.")

        _para(pdf, "Market Diligence Checklist", bold=True, size=11)
        _bullets(pdf, [
            "Validate total addressable market from bottom-up unit economics, not only top-down headlines.",
            "Separate volume growth from value growth; take-rate leakage can hide behind volume growth.",
            "Stress-test customer concentration, geographic exposure, and regulatory dependencies.",
            "Track capital intensity, working-capital needs, and free-cash-flow conversion as independent variables.",
        ])

        # ---------------- Forecast Model Snapshot ----------------
        pdf.add_page()
        _section_header(pdf, "Forecast Model Snapshot")
        headers, rows = _extract_financial_summary(fin or data)
        if rows:
            _render_table(pdf, headers, rows, align=["L"] + ["R"] * (len(headers) - 1))
        else:
            summary_rows = trends.get("summary") if isinstance(trends.get("summary"), list) else []
            if summary_rows:
                _render_table(
                    pdf,
                    ["Metric", "Latest Value"],
                    [[row.get("metric", "-"), _fmt(row.get("value"))] for row in summary_rows],
                    col_widths=[90, 88],
                )
            else:
                _para(pdf, "Financial trend data unavailable. Charts remain available in the application.")

        growth = fin.get("growth", {}) if isinstance(fin, dict) else {}
        if not growth and isinstance(data, dict):
            growth = data.get("growth", {})
        growth_rows = [
            ["Sales growth (3Y CAGR)", _pct(growth.get("sales_growth_3yr_pct"))],
            ["Sales growth (5Y CAGR)", _pct(growth.get("sales_growth_5yr_pct"))],
            ["Profit growth (3Y CAGR)", _pct(growth.get("profit_growth_3yr_pct"))],
            ["Profit growth (5Y CAGR)", _pct(growth.get("profit_growth_5yr_pct"))],
        ]
        _render_table(pdf, ["Growth Metric", "Value"], growth_rows, col_widths=[90, 88], align=["L", "R"])
        _para(pdf, "Model stance: Revenue and profit growth are read from historical filings; the investment case improves when growth is accompanied by stable or expanding returns on capital and positive free cash flow conversion.")

        # ---------------- Quality of Earnings Lenses ----------------
        pdf.add_page()
        _section_header(pdf, "Quality of Earnings Lenses")
        lenses = _quality_lenses(risks.get("flags") or [])
        _render_table(
            pdf,
            ["Lens", "Green Flag", "Yellow Flag", "Red Flag"],
            lenses,
            col_widths=[38, 50, 50, 40],
        )
        _para(pdf, "Use the lenses above together with the risk flags below. A single red flag does not invalidate the thesis, but it shifts the burden of proof to management disclosure and auditor quality.")

        # ---------------- Valuation and Scenarios ----------------
        pdf.add_page()
        _section_header(pdf, "Valuation and Scenarios")

        pdf.set_font("Helvetica", "B", 10)
        _set_color(pdf, C_HEADER)
        pdf.cell(0, 6, f"Current Price: {_fmt(current_price, 'Rs. ')}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, f"Fair Value Range: Rs. {_fmt(fair.get('low'))} - Rs. {_fmt(fair.get('base'))} - Rs. {_fmt(fair.get('high'))}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        _para(pdf, "Scenario Analysis", bold=True, size=11)
        scenarios = _build_scenarios(valuation)
        _render_table(
            pdf,
            ["Scenario", "Probability", "Growth / Thesis", "Implied Value", "Condition"],
            scenarios,
            col_widths=[22, 22, 52, 30, 52],
            align=["L", "R", "L", "R", "L"],
        )

        _para(pdf, "Valuation Method Mix", bold=True, size=11)
        method_rows = _build_valuation_methods(valuation)
        if method_rows:
            _render_table(
                pdf,
                ["Method", "Weight", "Core Assumption", "Fair Value"],
                method_rows,
                col_widths=[36, 20, 99, 30],
                align=["L", "R", "L", "R"],
            )
        else:
            _para(pdf, "Valuation method details unavailable.")

        # ---------------- Risks, Catalysts, and Monitoring Dashboard ----------------
        pdf.add_page()
        _section_header(pdf, "Risks, Catalysts, and Monitoring Dashboard")

        _para(pdf, "Monitoring Dashboard", bold=True, size=11)
        monitor_rows = [
            ["Revenue growth", "YoY sales / quarterly sales", "Positive", "Reassess growth multiple"],
            ["Margin trend", "OPM % trajectory", "Stable / expanding", "Cut margin assumption"],
            ["Leverage", "Debt / Equity vs peers", "Below peer median", "Reduce terminal margin"],
            ["Cash conversion", "OCF vs PAT", "OCF tracks PAT", "Delay re-rating case"],
            ["Governance", "Promoter pledge / auditor changes", "No red flags", "Move to bear-case inputs"],
        ]
        _render_table(
            pdf,
            ["Signal", "Monitor", "Target Zone", "Action if Breached"],
            monitor_rows,
            col_widths=[34, 50, 42, 52],
        )

        _para(pdf, "Catalyst Calendar", bold=True, size=11)
        catalysts = _lines_from_list(thesis.get("key_catalysts"))[:5]
        catalyst_rows = [[f"Catalyst {i + 1}", c, "May alter trajectory or valuation multiple"] for i, c in enumerate(catalysts)]
        if catalyst_rows:
            _render_table(
                pdf,
                ["Timing", "Catalyst", "Expected Thesis Impact"],
                catalyst_rows,
                col_widths=[26, 78, 74],
            )
        else:
            _para(pdf, "No catalysts available.")

        _para(pdf, "Top Risk Flags", bold=True, size=11)
        flags = risks.get("flags") or []
        flag_rows = [
            [f.get("status", "-").upper(), _safe_text(f.get("name"), 50), _safe_text(f.get("evidence"), 80)]
            for f in flags[:10]
        ]
        if flag_rows:
            _render_table(
                pdf,
                ["Status", "Flag", "Evidence"],
                flag_rows,
                col_widths=[22, 58, 98],
            )
        else:
            _para(pdf, "No risk flags evaluated.")

        # ---------------- Governance ----------------
        pdf.add_page()
        _section_header(pdf, "Governance")
        gov_rows = [
            ["Promoter Holding", _fmt(governance.get("promoter_holding"), "")],
            ["Promoter Trend", _safe_text(governance.get("promoter_trend"))],
            ["Pledged %", _fmt(governance.get("pledged_pct"), "")],
            ["FII Holding", _fmt(governance.get("fii_holding"), "")],
            ["DII Holding", _fmt(governance.get("dii_holding"), "")],
            ["Governance Score", _fmt(governance.get("governance_score"), "")],
        ]
        _render_table(pdf, ["Metric", "Value"], gov_rows, col_widths=[90, 88], align=["L", "R"])
        gov_flags = _lines_from_list(governance.get("flags"))
        if gov_flags:
            _para(pdf, "Governance Flags", bold=True, size=11)
            _bullets(pdf, gov_flags)

        # ---------------- Disclaimer ----------------
        pdf.add_page()
        _section_header(pdf, "Important Notice")
        _para(
            pdf,
            "This PDF is an illustrative institutional-style research report generated by the Stock Research Assistant. "
            "It uses structured market data, Screener.in financials, peer multiples, and simplified valuation models. "
            "It is not a recommendation, not a valuation opinion, and not a substitute for audited financial statements, "
            "broker research, SEBI-registered investment advice, or professional diligence. Verify all figures with official "
            "filings before making investment decisions.",
        )

        output = pdf.output(dest="S")
        if isinstance(output, bytes):
            return output
        if isinstance(output, bytearray):
            return bytes(output)
        return str(output).encode("latin-1", "replace")
    except Exception as exc:
        return _fallback_text_report(data, quick_result, deep_result, str(exc))
