from __future__ import annotations

import os
import json
import re
import http.cookiejar
import urllib.parse
import urllib.request
from html import escape
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit_shadcn_ui as ui

from logic import (
    resolve_ticker,
    suggest_tickers,
    ticker_not_found_message,
    to_nse_symbol,
    display_symbol,
    clamp_score,
    safe_float,
    money,
    number,
    pct,
    compute_rsi,
    compute_macd,
    local_scores,
    composite_score,
    verdict_for_score,
    parse_score,
)
from yf_client import (
    YFinanceRateLimitError,
    is_rate_limit_error,
    ticker_history,
    ticker_info,
)

from core.models import AgentResult, SCORE_ORDER
from services.analysis_pipeline import (
    fallback_result,
    build_context,
    run_agent,
    agent_or_fallback,
    run_agent_pipeline,
    run_local_pipeline,
    format_agent_outputs,
    build_local_summary,
    get_agent_output,
    run_analysis,
)
from payment import (
    _auth_user_id,
    _ensure_user_row,
    _supabase_offline,
    clear_auth,
    get_supabase_client,
    get_user,
    is_authenticated,
    load_auth,
    require_payment,
    REQUIRE_AUTH,
    save_auth,
    send_otp,
    track_usage,
    verify_otp,
)
from ui import (
    executive_verdict_strip,
    info_alert,
    kpi_card,
    page_header,
    sample_report_preview,
    score_card,
    section_title,
    status_pill,
    stock_header_card,
    verdict_badge,
)

from deep_research import run_deep_research
from deep_research.report import build_enhanced_pdf
from deep_research.screener_client import fetch_screener_financials
from services import report_history as report_history_service
from services.market_data import (
    load_market_data,
    _market_data_source_badge,
    _safe_ratio_name,
    _synthetic_history,
    _market_data_from_screener,
    _price_from_google_finance,
    _price_from_nse_quote_api,
    _price_from_ddgs_snippets,
    _current_price_from_web_sources,
    _current_price_from_web_search,
)
from services.error_logging import log_error


def inline_markdown_to_html(text: str) -> str:
    """Convert inline **bold** markdown to HTML, escaping other markup."""
    escaped = escape(str(text or ""))
    return re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", escaped)


def simple_markdown_to_html(text: str) -> str:
    """Convert simple markdown (paragraphs and bullet lists) to basic HTML."""
    lines = [line.rstrip() for line in str(text or "").splitlines()]
    html_lines: list[str] = []
    in_list = False
    for line in lines:
        if not line:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue
        if line.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{inline_markdown_to_html(line[2:])}</li>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<p>{inline_markdown_to_html(line)}</p>")
    if in_list:
        html_lines.append("</ul>")
    return "\n".join(html_lines)


APP_TITLE = "Stock Research Assistant"
QUICK_PICKS = {
    "SBIN": "State Bank of India",
    "RELIANCE": "Reliance Industries",
    "TCS": "Tata Consultancy Services",
}
REPORTS_DIR = Path(__file__).resolve().parent / "reports"
MAX_REPORT_FILES = 50
HISTORY_DISPLAY_LIMIT = 8

ROTATING_WIT = [
    "Good research takes time — we're digging through 20+ data sources for you.",
    "The best investors read more than they trade. Almost there.",
    "Crunching the numbers so you don't have to. Precision over speed.",
    "Quality analysis separates pros from gamblers. Stay with us.",
    "Building your edge — data beats gut feel, every single time.",
    "Deep work in progress. Every second here saves you hours of guesswork.",
]


st.set_page_config(page_title=APP_TITLE, page_icon="📊", layout="wide")


def inject_theme(theme: str = "light") -> None:
    is_light = theme == "light"
    st.markdown(
        f"""
        <style>
        :root {{
            --bg: {'#FFFFFF' if is_light else '#070b14'};
            --bg-2: {'#FAFAFA' if is_light else '#0b1220'};
            --panel: {'#FFFFFF' if is_light else 'rgba(15, 23, 42, 0.86)'};
            --panel-strong: {'#FFFFFF' if is_light else 'rgba(17, 24, 39, 0.96)'};
            --panel-soft: {'#F5F5F5' if is_light else 'rgba(30, 41, 59, 0.68)'};
            --border: {'#E8E8E8' if is_light else 'rgba(148, 163, 184, 0.20)'};
            --border-strong: {'#D0D0D0' if is_light else 'rgba(148, 163, 184, 0.34)'};
            --text: {'#1A1A1A' if is_light else '#f8fafc'};
            --muted: {'#4A4A4A' if is_light else '#a5b4c7'};
            --muted-2: {'#8A8A8A' if is_light else '#728097'};
            --green: {'#1DB954' if is_light else '#22c55e'};
            --red: {'#E53935' if is_light else '#ef4444'};
            --amber: {'#FFA000' if is_light else '#f59e0b'};
            --blue: {'#1DB954' if is_light else '#38bdf8'};
            --violet: {'#7C3AED' if is_light else '#a78bfa'};
            --shadow: {'0 4px 12px rgba(0, 0, 0, 0.08)' if is_light else '0 20px 60px rgba(0, 0, 0, 0.30)'};
            --radius-xl: 24px;
            --radius-lg: 18px;
            --radius-md: 12px;
        }}

        .stApp {{
            background: {'#FFFFFF' if is_light else '''
                radial-gradient(circle at top left, rgba(56, 189, 248, 0.18), transparent 30rem),
                radial-gradient(circle at top right, rgba(167, 139, 250, 0.16), transparent 26rem),
                linear-gradient(135deg, #050816 0%, #08111f 48%, #111827 100%)'''};
            color: var(--text);
        }}

        [data-testid="stAppViewContainer"] > .main {{
            padding-top: 3rem !important;
        }}

        .block-container {{
            max-width: 1280px;
            padding-top: 1.25rem;
            padding-bottom: 1.5rem;
        }}

        h1, h2, h3, h4, h5, h6, p, li, label, span, div {{
            color: var(--text);
        }}

        h1 {{
            letter-spacing: -0.02em;
            line-height: 1.1;
        }}

        a {{ color: var(--blue); }}

        [data-testid="stSidebar"] {{
            background: {'#FAFAFA' if is_light else 'linear-gradient(180deg, rgba(8, 13, 25, 0.98), rgba(10, 17, 31, 0.98))'};
            border-right: 1px solid var(--border);
        }}

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] span {{
            color: var(--muted);
        }}
        """,
        unsafe_allow_html=True,
    )
    # Inject remaining CSS from the original block, letting it use the CSS variables above.
    _inject_component_styles(theme)


def _inject_component_styles(theme: str) -> None:
    is_light = theme == "light"
    st.markdown(
        """
        <style>
        .sidebar-brand {
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.16), rgba(34, 197, 94, 0.08));
            padding: 1rem;
            margin: 0.35rem 0 1rem;
            box-shadow: var(--shadow);
        }
        .sidebar-brand .logo {
            align-items: center;
            background: var(--panel-soft);
            border: 1px solid var(--border);
            border-radius: 14px;
            display: inline-flex;
            font-size: 1.15rem;
            height: 2.3rem;
            justify-content: center;
            margin-bottom: 0.65rem;
            width: 2.3rem;
        }
        """
        + ("""
        /* Light theme adjustments — Ali Abdaal style */
        .sidebar-brand {
            background: #FFFFFF !important;
            border: 1px solid #E8E8E8 !important;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
        }
        .sidebar-brand .logo {
            background: #F5F5F5 !important;
        }
        .hero-card {
            background: #FFFFFF;
            border: 1px solid #E8E8E8;
        }
        .hero-aside {
            background: #F5F5F5;
            border: 1px solid #E8E8E8;
        }
        .sample-report-preview {
            background: #FFFFFF;
            border: 1px solid #E8E8E8;
        }
        .executive-verdict-strip {
            background: #FFFFFF;
            border: 1px solid #E8E8E8;
        }
        .sidebar-premium-card, .sidebar-help-card, .recent-analysis-item {
            background: #F5F5F5;
            border: 1px solid #E8E8E8;
        }
        .stButton button[kind="primary"] {
            background: #1DB954 !important;
            border-color: #1DB954 !important;
            color: #FFFFFF !important;
        }
        .stButton button[kind="primary"] p,
        .stButton button[kind="primary"] span {
            color: #FFFFFF !important;
        }
        """ if is_light else ""),
        unsafe_allow_html=True,
    )
    # ── Comprehensive light-theme override for all dark hardcoded backgrounds ──
    if is_light:
        st.markdown(
            """
            <style>
            /* Ali Abdaal light theme: override all dark-tile backgrounds */
            .sidebar-brand .logo { background: #F0F0F0 !important; border-color: #E8E8E8 !important; box-shadow: none !important; color: #1A1A1A !important; text-shadow: none !important; }
            .sidebar-help-card { background: #F5F5F5 !important; }
            .recent-analysis-item { background: #F5F5F5 !important; }
            .hero-card { background: #FFFFFF !important; box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important; }
            .status-pill { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            .empty-preview-card { background: #FFFFFF !important; box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important; }
            .empty-state-icon { background: rgba(29,185,84,0.10) !important; border-color: rgba(29,185,84,0.20) !important; }
            .empty-step b { background: rgba(29,185,84,0.10) !important; border-color: rgba(29,185,84,0.20) !important; color: #1DB954 !important; }
            .footer { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            .stTextInput input { background: #FFFFFF !important; border-color: #E8E8E8 !important; color: #1A1A1A !important; }
            .stTextInput input:focus { border-color: #1DB954 !important; box-shadow: 0 0 0 3px rgba(29,185,84,0.12) !important; }
            [data-testid="stSidebar"] div.stButton > button { background: #FFFFFF !important; border-color: #E8E8E8 !important; color: #1A1A1A !important; }
            [data-testid="stSidebar"] div.stButton > button:hover { background: #F5F5F5 !important; border-color: #1DB954 !important; }
            [data-testid="stSidebar"] button[kind="primary"] { background: #1DB954 !important; border-color: #1DB954 !important; color: #FFFFFF !important; }
            [data-testid="stSidebar"] button[kind="primary"]:hover { background: #1ED760 !important; }
            [data-testid="stSidebarContent"] { scrollbar-color: rgba(29,185,84,0.3) #F0F0F0 !important; }
            [data-testid="stSidebarContent"]::-webkit-scrollbar-track { background: #F0F0F0 !important; }
            [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb { background: rgba(29,185,84,0.3) !important; }
            [data-testid="stSidebar"] hr { border-color: #E8E8E8 !important; }
            .sidebar-brand { background: #FFFFFF !important; border-color: #E8E8E8 !important; box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important; }
            div[data-testid="stPlotlyChart"] { box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important; border-color: #E8E8E8 !important; }
            .page-header::after { background: linear-gradient(90deg, #1DB954, #1ED760, #7C3AED) !important; }
            button[kind="primary"] { background: #1DB954 !important; border-color: #1DB954 !important; }
            .sidebar-premium-card { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            .hero-chip-row span { background: #F5F5F5 !important; border-color: #E8E8E8 !important; color: #4A4A4A !important; }
            .empty-step { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            .empty-state { background: #FFFFFF !important; border-color: #E8E8E8 !important; }
            /* Additional dark-bg overrides */
            .sidebar-brand .logo { background: #F0F0F0 !important; border-color: #E8E8E8 !important; }
            .status-pill { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            .footer { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            .hero-aside strong { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            [data-testid="stSidebar"] [data-testid="stAlert"] { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            [data-testid="stSidebar"] button[aria-label="Send OTP"] { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            .stTextInput input { background: #FFFFFF !important; border-color: #E8E8E8 !important; }
            .sidebar-premium-card { background: #F5F5F5 !important; border-color: #E8E8E8 !important; }
            /* Force Streamlit native elements to light */
            [data-testid="stMetric"] { background: #FFFFFF !important; border-color: #E8E8E8 !important; }
            [data-testid="stMetricValue"] { color: #1A1A1A !important; }
            [data-testid="stMetricLabel"] { color: #4A4A4A !important; }
            [data-testid="stMetricDelta"] { color: #1DB954 !important; }
            [data-testid="stDataFrame"] { background: #FFFFFF !important; }
            .stAlert { background: #F5F5F5 !important; border-color: #E8E8E8 !important; color: #1A1A1A !important; }
            .stTabs [role="tablist"] { background: #F5F5F5 !important; }
            [data-testid="stTooltip"] { background: #FFFFFF !important; border-color: #E8E8E8 !important; color: #1A1A1A !important; }
            /* Expander and container overrides */
            .streamlit-expanderHeader { background: #F5F5F5 !important; color: #1A1A1A !important; }
            details summary { color: #1A1A1A !important; }
            [data-testid="stExpander"] { background: #FFFFFF !important; border-color: #E8E8E8 !important; }
            /* Result section cards */
            .executive-verdict-strip { background: #FFFFFF !important; border-color: #E8E8E8 !important; }
            .score-card { background: #FFFFFF !important; border-color: #E8E8E8 !important; }
            .score-bar { background: #F0F0F0 !important; }
            .verdict-badge { background: #FFFFFF !important; border-color: #E8E8E8 !important; }
            /* Remaining dark-element overrides */
            .hero-workflow-step { background: #F5F5F5 !important; border-color: #E8E8E8 !important; color: #1A1A1A !important; }
            .hero-workflow-step em { background: #F0F0F0 !important; color: #1A1A1A !important; }
            .sample-report-section-pill { background: #F0F0F0 !important; color: #4A4A4A !important; }
            article { background: #FFFFFF !important; border-color: #E8E8E8 !important; }
            [data-testid="stBaseButton-secondary"] { background: #FFFFFF !important; border-color: #E8E8E8 !important; color: #1A1A1A !important; }
            .hero-chip-row span { background: #F0F0F0 !important; color: #4A4A4A !important; border-color: #E8E8E8 !important; }
            /* Ensure all text is dark in light mode */
            .hero-workflow-step, .hero-workflow-step *, .sample-report-section-pill, .sample-report-section-pill * { color: #1A1A1A !important; }
            /* High-specificity overrides for stubborn dark elements */
            .hero-chip-row > span { background: #F0F0F0 !important; color: #4A4A4A !important; border-color: #E8E8E8 !important; }
            .hero-proof-row em { background: #F0F0F0 !important; color: #4A4A4A !important; border: 1px solid #E8E8E8 !important; border-radius: 6px !important; padding: 2px 8px !important; font-style: normal !important; }
            [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] { background: #FFFFFF !important; border-color: #E8E8E8 !important; color: #1A1A1A !important; }
            .stButton [data-testid="stBaseButton-secondary"] { background: #FFFFFF !important; border-color: #E8E8E8 !important; color: #1A1A1A !important; }
            /* Force sidebar Run Report button light */
            [data-testid="stSidebar"] .stButton [data-testid="stBaseButton-secondary"],
            [data-testid="stSidebar"] button[kind="secondary"] { background: #FFFFFF !important; border-color: #E8E8E8 !important; color: #1A1A1A !important; }
            </style>
            """,
            unsafe_allow_html=True,
        )
    st.markdown(
        """
        <style>
        .sidebar-brand h2 {
            font-size: 1.05rem;
            margin: 0 0 0.25rem;
            line-height: 1.15;
        }
        .sidebar-brand p, .sidebar-help-card p {
            color: var(--muted);
            font-size: 0.86rem;
            line-height: 1.45;
            margin: 0;
        }
        .sidebar-section-title {
            color: var(--text);
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            margin: 1rem 0 0.45rem;
            text-transform: uppercase;
        }
        .sidebar-help-card {
            background: var(--panel-soft);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            padding: 0.78rem;
            margin-top: 0.8rem;
        }
        .recent-analysis-item {
            background: var(--panel-soft);
            border: 1px solid var(--border);
            border-radius: 12px;
            margin: 0.45rem 0;
            padding: 0.65rem 0.7rem;
        }
        .recent-analysis-item strong {
            color: var(--text);
            display: block;
            font-size: 0.9rem;
        }
        .recent-analysis-item span {
            color: var(--muted);
            font-size: 0.78rem;
        }

        .hero-card {
            background:
                linear-gradient(135deg, rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.72)),
                radial-gradient(circle at 15% 10%, rgba(56, 189, 248, 0.22), transparent 24rem);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            box-shadow: var(--shadow);
            overflow: hidden;
            position: relative;
        }
        .page-header {
            align-items: stretch;
            display: flex;
            gap: 1rem;
            justify-content: space-between;
            margin-bottom: 1.25rem;
            padding: 1.35rem;
        }
        .page-header::after {
            background: linear-gradient(90deg, rgba(56,189,248,0.55), rgba(34,197,94,0.45), rgba(167,139,250,0.45));
            bottom: 0;
            content: "";
            height: 2px;
            left: 0;
            position: absolute;
            right: 0;
        }
        .eyebrow {
            color: var(--blue);
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
        }
        .page-header h1 {
            font-size: clamp(2rem, 4vw, 3.25rem);
            font-weight: 900;
            letter-spacing: -0.02em;
            line-height: 1.1;
            margin: 0;
        }
        .page-header p {
            color: var(--muted);
            font-size: 1rem;
            line-height: 1.55;
            margin: 0.65rem 0 0;
            max-width: 760px;
        }
        .hero-chip-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 1rem;
        }
        .hero-chip-row span {
            background: rgba(148, 163, 184, 0.11);
            border: 1px solid var(--border);
            border-radius: 999px;
            color: var(--muted);
            font-size: 0.78rem;
            padding: 0.35rem 0.6rem;
        }
        .hero-aside {
            align-self: stretch;
            background: var(--panel-soft);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            min-width: 270px;
            padding: 1rem;
        }
        .hero-aside-label {
            color: var(--muted-2);
            font-size: 0.76rem;
            font-weight: 800;
            letter-spacing: 0.1em;
            margin-bottom: 0.6rem;
            text-transform: uppercase;
        }
        .hero-aside strong {
            display: block;
            font-size: 1rem;
            line-height: 1.35;
        }
        .hero-aside small {
            color: var(--muted);
            display: block;
            line-height: 1.45;
            margin-top: 0.55rem;
        }

        .stock-header-card,
        .empty-state,
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--panel);
            border-color: var(--border) !important;
            border-radius: var(--radius-lg) !important;
            box-shadow: var(--shadow);
        }
        .stock-header-card {
            border: 1px solid var(--border);
            padding: 1.15rem;
        }
        .stock-meta-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 0.85rem;
        }
        .stock-meta-row span,
        .stock-symbol,
        .muted {
            color: var(--muted);
            font-size: 0.86rem;
        }
        .stock-meta-row span {
            background: rgba(148, 163, 184, 0.10);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.28rem 0.55rem;
        }
        .stock-title-row {
            align-items: flex-end;
            display: flex;
            gap: 1rem;
            justify-content: space-between;
        }
        .stock-title-row h2 {
            font-size: clamp(1.35rem, 2.4vw, 2rem);
            font-weight: 850;
            letter-spacing: -0.03em;
            line-height: 1.12;
            margin: 0.2rem 0 0;
        }
        .stock-price-block {
            min-width: 190px;
            text-align: right;
        }
        .stock-price {
            font-size: clamp(1.8rem, 3.2vw, 2.55rem);
            font-weight: 900;
            letter-spacing: -0.04em;
            line-height: 1;
        }
        .positive { color: var(--green); font-weight: 800; }
        .negative { color: var(--red); font-weight: 800; }
        .neutral { color: var(--amber); font-weight: 800; }

        .section-title-wrap {
            align-items: center;
            display: flex;
            margin: 1.35rem 0 0.75rem;
        }
        .section-title {
            font-size: 1.06rem;
            font-weight: 850;
            letter-spacing: -0.015em;
            line-height: 1.25;
            margin: 0;
        }
        .section-title-wrap::after {
            background: linear-gradient(90deg, var(--border-strong), transparent);
            content: "";
            flex: 1;
            height: 1px;
            margin-left: 0.75rem;
        }

        .score-bar {
            background: rgba(148, 163, 184, 0.16);
            border-radius: 999px;
            height: 7px;
            margin-top: -0.45rem;
            overflow: hidden;
        }
        .score-bar span {
            border-radius: 999px;
            display: block;
            height: 100%;
        }
        .score-pill { margin-top: 0.35rem; }
        .verdict-badge { margin: 0.35rem 0 0.7rem; }
        .status-pill {
            align-items: center;
            background: var(--panel-soft);
            border: 1px solid var(--border);
            border-radius: 999px;
            display: flex;
            gap: 0.55rem;
            justify-content: space-between;
            margin-top: 0.55rem;
            padding: 0.42rem 0.7rem;
        }
        .status-pill span {
            color: var(--muted);
            font-size: 0.78rem;
        }
        .status-pill strong {
            font-size: 0.82rem;
            text-transform: uppercase;
        }

        .empty-state {
            border: 1px solid var(--border);
            padding: 2rem;
            text-align: center;
        }
        .empty-state-icon {
            align-items: center;
            background: rgba(56, 189, 248, 0.14);
            border: 1px solid rgba(56, 189, 248, 0.26);
            border-radius: 18px;
            display: inline-flex;
            font-size: 1.8rem;
            height: 4rem;
            justify-content: center;
            margin-bottom: 1rem;
            width: 4rem;
        }
        .empty-state h3 {
            font-size: 1.35rem;
            margin: 0 0 0.4rem;
        }
        .empty-state p {
            color: var(--muted);
            margin: 0 auto;
            max-width: 620px;
        }
        .empty-state ol {
            color: var(--muted);
            display: inline-block;
            line-height: 1.8;
            margin: 1rem auto 0;
            text-align: left;
        }
        .empty-preview-grid {
            display: grid;
            gap: 0.85rem;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin: 1rem 0 1.25rem;
        }
        .empty-preview-card {
            background: rgba(15, 23, 42, 0.78);
            border: 1px solid var(--border);
            border-left: 4px solid var(--accent);
            border-radius: var(--radius-md);
            padding: 0.95rem;
            min-height: 112px;
            box-shadow: 0 14px 34px rgba(0, 0, 0, 0.20);
        }
        .empty-preview-card span {
            color: var(--muted);
            display: block;
            font-size: 0.78rem;
            font-weight: 800;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .empty-preview-card strong {
            color: var(--text);
            display: block;
            font-size: 1.45rem;
            letter-spacing: -0.02em;
            line-height: 1.05;
            margin-top: 0.45rem;
        }
        .empty-preview-card small {
            color: var(--muted);
            display: block;
            line-height: 1.4;
            margin-top: 0.45rem;
        }
        .empty-preview-card.positive small { color: rgba(34, 197, 94, 0.92); }
        .empty-preview-card.negative small { color: rgba(239, 68, 68, 0.92); }
        .empty-preview-card.neutral small { color: rgba(245, 158, 11, 0.92); }
        .empty-steps {
            display: grid;
            gap: 0.75rem;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            margin-top: 0.9rem;
        }
        .hero-aside {
            align-self: stretch;
            background: var(--panel-soft);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            min-width: 270px;
            padding: 1rem;
        }
        .empty-step {
            align-items: center;
            background: var(--panel-soft);
            border: 1px solid var(--border);
            border-radius: var(--radius-md);
            display: flex;
            gap: 0.65rem;
            padding: 0.78rem;
        }
        .empty-step b {
            align-items: center;
            background: rgba(56, 189, 248, 0.14);
            border: 1px solid rgba(56, 189, 248, 0.26);
            border-radius: 999px;
            display: inline-flex;
            flex: 0 0 1.8rem;
            height: 1.8rem;
            justify-content: center;
            width: 1.8rem;
        }
        .empty-step span {
            color: var(--muted);
            font-size: 0.86rem;
            line-height: 1.35;
        }

        div[data-testid="stPlotlyChart"] {
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            overflow: hidden;
            box-shadow: 0 16px 42px rgba(0, 0, 0, 0.22);
        }
        div[data-testid="stTabs"] button p {
            font-weight: 750;
        }
        .stTextInput input {
            background: rgba(15, 23, 42, 0.82) !important;
            border: 1px solid var(--border) !important;
            border-color: rgba(255,255,255,0.15) !important;
            border-radius: 12px !important;
            color: var(--text) !important;
        }
        .stTextInput input:focus {
            border-color: rgba(56, 189, 248, 0.72) !important;
            box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.25) !important;
        }
        div.stButton > button,
        button[kind="primary"] {
            border-radius: 12px !important;
            font-weight: 800 !important;
        }
        button[kind="primary"] {
            background: linear-gradient(135deg, #16a34a, #22c55e) !important;
            border: 1px solid rgba(34, 197, 94, 0.95) !important;
        }
        [data-testid="stSidebar"] div.stButton > button {
            background: rgba(15, 23, 42, 0.82) !important;
            border: 1px solid rgba(148, 163, 184, 0.28) !important;
            color: var(--text) !important;
            justify-content: flex-start !important;
            min-height: 2.35rem;
            width: 100%;
        }
        [data-testid="stSidebar"] div.stButton > button:hover {
            background: rgba(30, 41, 59, 0.92) !important;
            border-color: rgba(56, 189, 248, 0.48) !important;
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] button[kind="primary"] {
            background: rgba(15, 23, 42, 0.82) !important;
            border: 1px solid rgba(148, 163, 184, 0.28) !important;
            color: var(--text) !important;
            justify-content: center !important;
        }
        [data-testid="stSidebar"] button[kind="primary"]:hover {
            background: rgba(30, 41, 59, 0.92) !important;
            border-color: rgba(56, 189, 248, 0.48) !important;
            color: #ffffff !important;
        }
        .footer {
            background: rgba(15, 23, 42, 0.62);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            color: var(--muted);
            margin-top: 1.5rem;
            padding: 0.85rem 1rem;
            text-align: center;
            font-size: 0.88rem;
        }
        .footer strong { color: var(--text); }

        @media (max-width: 860px) {
            .page-header {
                flex-direction: column;
                padding: 1.05rem;
            }
            .hero-aside {
                min-width: unset;
            }
            .stock-title-row {
                align-items: flex-start;
                flex-direction: column;
            }
            .stock-price-block {
                text-align: left;
            }
            .block-container {
                padding-left: 0.85rem;
                padding-right: 0.85rem;
            }
            .empty-preview-grid,
            .empty-steps {
                grid-template-columns: 1fr;
            }
        }

        /* ── Fix 1: Letter-spacing on headings ── */
        h1 { letter-spacing: -0.02em !important; font-weight: 800 !important; }
        h2 { letter-spacing: -0.01em !important; }
        .empty-state h2, [data-testid="stHeading"] h2 { letter-spacing: -0.01em !important; }

        /* ── Fix 2: Collapse dead vertical space ── */
        .block-container { padding-top: 2rem !important; padding-bottom: 2rem !important; }
        [data-testid="stVerticalBlock"] > div { gap: 1.5rem !important; }

        /* ── Fix 3: Tab active state ── */
        .stTabs [aria-selected="true"] { 
            background: rgba(29, 185, 84, 0.12) !important; 
            color: var(--blue) !important; 
            border-bottom: 2px solid var(--blue) !important; 
        }
        .stTabs [data-baseweb="tab"]:hover { color: var(--blue) !important; }

        /* ── Fix 4: Softer input borders ── */
        [data-baseweb="input"] { 
            border: 1px solid var(--border) !important; 
            border-radius: 8px !important; 
            background: var(--panel-soft) !important; 
        }
        [data-baseweb="input"]:focus {
            border-color: var(--blue) !important;
            box-shadow: 0 0 0 1px var(--blue) !important;
        }

        /* ── Fix 5: Button hover + polish ── */
        .stButton button { 
            border: 1px solid var(--border) !important; 
            border-radius: 8px !important;
            transition: all 0.2s !important;
            padding: 0.5rem 1rem !important;
            margin-bottom: 0.4rem !important;
        }
        .stButton button:hover { 
            border-color: var(--blue) !important; 
            background: rgba(29, 185, 84, 0.08) !important; 
        }

        /* ── Fix 6: Primary button (Analyze) ── */
        .stButton button[kind="primary"] {
            background: var(--blue) !important;
            border-color: var(--blue) !important;
            color: white !important;
            font-weight: 700 !important;
        }
        .stButton button[kind="primary"]:hover {
            background: var(--blue) !important;
            border-color: var(--blue) !important;
            filter: brightness(1.1);
        }

        /* ── Fix 7: Label readability ── */
        .stCaption, [data-testid="stCaptionContainer"] { 
            font-size: 0.7rem !important; 
            letter-spacing: 0.08em !important; 
            font-weight: 600 !important; 
            color: var(--muted-2) !important;
        }

        /* ── Fix 8: Body text contrast ── */
        p, .stMarkdown p { color: var(--muted) !important; line-height: 1.6 !important; }

        /* ── Fix 9: CSS variables for semantic colors ── */
        :root {
            --primary: var(--blue);
            --positive: var(--green);
            --negative: var(--red);
            --neutral: var(--muted-2);
        }

        /* ── Fix 10: Empty state icon glow ── */
        .empty-icon { box-shadow: 0 0 24px rgba(29, 185, 84, 0.15) !important; }

        /* ── Fix 11: Card padding consistency ── */
        [data-testid="stVerticalBlockBorderWrapper"] { padding: 1.5rem 1.75rem !important; }

        /* ── Active tab pill with filled state ── */
        .stTabs [data-baseweb="tab"] {
            border-radius: 8px !important;
            padding: 0.4rem 1rem !important;
            margin: 0 0.25rem !important;
            background: var(--panel-soft) !important;
            border: 1px solid var(--border) !important;
            transition: all 0.2s !important;
        }
        .stTabs [aria-selected="true"] {
            background: rgba(96,165,250,0.18) !important;
            color: #60a5fa !important;
            border: 1px solid #60a5fa !important;
            font-weight: 600 !important;
        }
        .stTabs [data-baseweb="tab"]:hover {
            background: rgba(96,165,250,0.08) !important;
            border-color: #60a5fa !important;
        }
        .stTabs [data-baseweb="tab-highlight"] {
            display: none !important;
        }

        /* ── Production polish pass: chrome, sidebar reachability, and dashboard depth ── */
        /* Mobile: expose a 96px left rail so Streamlit's native sidebar toggle is easy to tap. */
        @media (max-width: 768px) {
            [data-testid="stSidebar"] {
                width: min(340px, 88vw) !important;
                max-width: 88vw !important;
                transform: translateX(calc(-1 * (min(340px, 88vw) - 96px))) !important;
                transition: transform 0.25s ease !important;
                z-index: 999998 !important;
            }
            [data-testid="stSidebar"][aria-expanded="true"] {
                transform: translateX(0) !important;
            }
            [data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] {
                align-items: center !important;
                display: flex !important;
                height: 56px !important;
                justify-content: center !important;
                left: auto !important;
                min-height: 56px !important;
                min-width: 56px !important;
                position: absolute !important;
                right: 0.75rem !important;
                top: 0.5rem !important;
                width: 56px !important;
                z-index: 999999 !important;
            }
            [data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] button,
            [data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] [role="button"] {
                align-items: center !important;
                border-radius: 14px !important;
                display: flex !important;
                height: 56px !important;
                justify-content: center !important;
                min-height: 56px !important;
                min-width: 56px !important;
                width: 56px !important;
            }
            [data-testid="stSidebar"] [data-testid="stSidebarCollapseButton"] span {
                font-size: 1.65rem !important;
                line-height: 1 !important;
            }
        }

        [data-testid="stAppViewContainer"] {
            background: var(--bg-2) !important;
        }
        [data-testid="stAppViewContainer"] > .main {
            padding-top: 0 !important;
        }
        .block-container {
            padding-top: 1.25rem !important;
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0b1220 0%, #070b14 100%) !important;
            box-shadow: 18px 0 44px rgba(0, 0, 0, 0.22);
            height: 100dvh !important;
            overflow: hidden !important;
        }
        [data-testid="stSidebarContent"] {
            height: 100dvh !important;
            max-height: 100dvh !important;
            overflow-y: auto !important;
            padding-bottom: 4.5rem !important;
            scrollbar-color: rgba(56, 189, 248, 0.42) rgba(15, 23, 42, 0.42);
            scrollbar-width: thin;
        }
        [data-testid="stSidebarContent"]::-webkit-scrollbar {
            width: 8px;
        }
        [data-testid="stSidebarContent"]::-webkit-scrollbar-track {
            background: rgba(15, 23, 42, 0.44);
        }
        [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb {
            background: rgba(56, 189, 248, 0.42);
            border-radius: 999px;
        }
        [data-testid="stSidebar"] hr {
            border-color: rgba(148, 163, 184, 0.18) !important;
            margin: 0.85rem 0 !important;
        }

        .sidebar-brand {
            background:
                radial-gradient(circle at 18% 12%, rgba(56, 189, 248, 0.28), transparent 7rem),
                linear-gradient(145deg, rgba(15, 23, 42, 0.96), rgba(8, 13, 25, 0.92)) !important;
            border-color: rgba(56, 189, 248, 0.24) !important;
            box-shadow: 0 18px 46px rgba(0, 0, 0, 0.34), inset 0 1px 0 rgba(255, 255, 255, 0.06) !important;
        }
        .sidebar-brand .logo {
            background: linear-gradient(135deg, var(--blue), var(--green)) !important;
            border-color: rgba(255, 255, 255, 0.18) !important;
            box-shadow: 0 14px 32px rgba(56, 189, 248, 0.28), 0 0 0 6px rgba(56, 189, 248, 0.08);
            color: #03111d !important;
            text-shadow: 0 1px 0 rgba(255, 255, 255, 0.28);
        }

        [data-testid="stSidebar"] .stTextInput input,
        [data-testid="stSidebar"] [data-baseweb="input"] input {
            background: var(--panel-soft) !important;
            border: 1px solid var(--border) !important;
            border-radius: 12px !important;
            box-shadow: inset 0 1px 0 rgba(0, 0, 0, 0.04) !important;
            color: var(--text) !important;
            min-height: 2.55rem !important;
        }
        [data-testid="stSidebar"] .stTextInput input::placeholder {
            color: var(--muted-2) !important;
        }
        [data-testid="stSidebar"] .stTextInput input:focus,
        [data-testid="stSidebar"] [data-baseweb="input"]:focus-within {
            border-color: var(--blue) !important;
            box-shadow: 0 0 0 3px rgba(29, 185, 84, 0.16), inset 0 1px 0 rgba(0, 0, 0, 0.05) !important;
        }
        [data-testid="stSidebar"] div.stButton > button,
        [data-testid="stSidebar"] button[kind="secondary"] {
            background: var(--panel-soft) !important;
            border: 1px solid var(--border) !important;
            border-radius: 12px !important;
            color: var(--text) !important;
            font-weight: 750 !important;
            min-height: 2.45rem !important;
            transition: background 160ms ease, border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease !important;
        }
        [data-testid="stSidebar"] div.stButton > button:hover,
        [data-testid="stSidebar"] button[kind="secondary"]:hover {
            background: var(--panel-strong) !important;
            border-color: var(--blue) !important;
            box-shadow: 0 10px 24px rgba(0, 0, 0, 0.08), 0 0 0 3px rgba(29, 185, 84, 0.10) !important;
            color: var(--text) !important;
            transform: translateY(-1px);
        }
        [data-testid="stSidebar"] button[kind="primary"],
        [data-testid="stSidebar"] div.stButton > button[kind="primary"] {
            background: var(--blue) !important;
            border-color: var(--blue) !important;
            box-shadow: 0 14px 28px rgba(0, 0, 0, 0.12) !important;
            color: #FFFFFF !important;
            justify-content: center !important;
        }
        [data-testid="stSidebar"] button[kind="primary"]:hover,
        [data-testid="stSidebar"] div.stButton > button[kind="primary"]:hover {
            background: var(--blue) !important;
            border-color: var(--blue) !important;
            filter: brightness(1.1);
            box-shadow: 0 16px 32px rgba(0, 0, 0, 0.10), 0 0 0 3px rgba(29, 185, 84, 0.14) !important;
        }

        .hero-chip-row span {
            background: var(--panel-soft) !important;
            border: 1px solid var(--border) !important;
            box-shadow: inset 0 1px 0 rgba(0, 0, 0, 0.04);
            color: var(--muted) !important;
            cursor: default !important;
        }
        .hero-aside {
            align-self: center !important;
            background: var(--panel-soft) !important;
            border: 1px solid var(--border) !important;
            box-shadow: inset 0 1px 0 rgba(0, 0, 0, 0.04), 0 16px 34px var(--shadow);
            min-width: 315px !important;
            padding: 0.85rem !important;
        }
        .hero-aside-label {
            margin-bottom: 0.45rem !important;
        }
        .hero-aside strong {
            background: var(--panel-soft);
            border: 1px solid var(--border);
            border-radius: 999px;
            color: var(--text);
            display: inline-flex !important;
            font-size: 0.86rem !important;
            gap: 0.35rem;
            line-height: 1.2 !important;
            padding: 0.48rem 0.65rem;
            white-space: nowrap;
        }
        .hero-aside small {
            color: var(--muted) !important;
            font-size: 0.78rem;
            margin-top: 0.5rem !important;
        }

        .empty-state {
            background:
                radial-gradient(circle at 50% 4rem, rgba(56, 189, 248, 0.16), transparent 12rem),
                linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.76)) !important;
            box-shadow: 0 24px 70px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
            padding: 2.35rem 1.75rem !important;
        }
        .empty-state-icon {
            background:
                radial-gradient(circle, rgba(56, 189, 248, 0.34), rgba(59, 130, 246, 0.14) 58%, rgba(15, 23, 42, 0.86) 100%) !important;
            border-color: rgba(125, 211, 252, 0.34) !important;
            border-radius: 24px !important;
            box-shadow: 0 0 0 10px rgba(56, 189, 248, 0.055), 0 0 44px rgba(56, 189, 248, 0.26) !important;
            font-size: 2.35rem !important;
            height: 5.35rem !important;
            margin-bottom: 1.1rem !important;
            width: 5.35rem !important;
        }
        .empty-state h3 {
            font-size: clamp(1.55rem, 2.3vw, 2rem) !important;
            letter-spacing: -0.015em !important;
        }
        .empty-state p {
            color: #cbd5e1 !important;
            line-height: 1.5 !important;
            max-width: 560px !important;
        }
        .empty-state ol {
            margin-top: 0.85rem !important;
        }
        .empty-preview-card,
        .empty-step {
            box-shadow: 0 16px 38px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
        }
        .empty-preview-card {
            background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(2, 6, 23, 0.52)) !important;
        }
        .empty-preview-card small::after {
            color: var(--blue);
            content: "  Try analyzing \2192";
            display: block;
            font-weight: 800;
            margin-top: 0.35rem;
        }

        [data-testid="stSidebar"] [data-testid="stAlert"] {
            background: rgba(15, 23, 42, 0.86) !important;
            border: 1px solid rgba(148, 163, 184, 0.22) !important;
            border-left: 4px solid var(--green) !important;
            border-radius: 14px !important;
            box-shadow: 0 12px 26px rgba(2, 6, 23, 0.22) !important;
            color: #dbeafe !important;
            padding: 0.48rem 0.7rem !important;
        }
        [data-testid="stSidebar"] [data-testid="stAlert"] p,
        [data-testid="stSidebar"] [data-testid="stAlert"] div {
            color: #dbeafe !important;
            font-size: 0.82rem !important;
            line-height: 1.3 !important;
        }

        @media (max-width: 860px) {
            .hero-aside {
                min-width: unset !important;
                width: 100%;
            }
            .hero-aside strong {
                white-space: normal;
            }
        }

        /* Targeted UI polish pass 2: sidebar email CTA and static hero tags */
        /* Send OTP is a secondary gating action; keep it visible but do not compete with the main Generate CTA. */
        [data-testid="stSidebar"] .st-key-send_otp_button button,
        [data-testid="stSidebar"] div[data-testid="stButton"][class*="send_otp_button"] button,
        [data-testid="stSidebar"] button[aria-label="Send OTP"] {
            background: rgba(15, 23, 42, 0.82) !important;
            border: 1px solid rgba(148, 163, 184, 0.28) !important;
            border-radius: 12px !important;
            box-shadow: none !important;
            color: var(--text) !important;
            font-weight: 800 !important;
            justify-content: center !important;
            min-height: 2.35rem !important;
            text-shadow: none;
            transform: translateY(0);
            transition: all 160ms ease !important;
        }
        [data-testid="stSidebar"] .st-key-send_otp_button button *,
        [data-testid="stSidebar"] div[data-testid="stButton"][class*="send_otp_button"] button *,
        [data-testid="stSidebar"] button[aria-label="Send OTP"] * {
            color: var(--text) !important;
            font-weight: 800 !important;
        }
        [data-testid="stSidebar"] .st-key-send_otp_button button:hover,
        [data-testid="stSidebar"] div[data-testid="stButton"][class*="send_otp_button"] button:hover,
        [data-testid="stSidebar"] button[aria-label="Send OTP"]:hover {
            background: rgba(30, 41, 59, 0.92) !important;
            border-color: rgba(56, 189, 248, 0.48) !important;
            color: #ffffff !important;
            box-shadow: none !important;
            filter: none;
            transform: translateY(-1px);
        }

        .hero-chip-row span {
            background: var(--panel-soft) !important;
            border: 1px solid var(--border) !important;
            border-left-width: 2px !important;
            border-radius: 999px !important;
            box-shadow: none !important;
            color: var(--muted) !important;
            cursor: default !important;
            font-size: 0.69rem !important;
            font-weight: 650 !important;
            letter-spacing: 0 !important;
            line-height: 1.15 !important;
            padding: 0.28rem 0.52rem !important;
            pointer-events: none !important;
        }
        .hero-chip-row span:nth-child(1) { border-left-color: #38bdf8 !important; }
        .hero-chip-row span:nth-child(2) { border-left-color: #22c55e !important; }
        .hero-chip-row span:nth-child(3) { border-left-color: #f59e0b !important; }
        .hero-chip-row span:nth-child(4) { border-left-color: #ef4444 !important; }

        /* Specificity override: Streamlit's sidebar secondary-button rule is stronger than key-only selectors. */
        [data-testid="stSidebar"] .stElementContainer.st-key-send_otp_button div.stButton > button[kind="secondary"] {
            background: var(--panel-soft) !important;
            border: 1px solid var(--border) !important;
            box-shadow: none !important;
            color: var(--text) !important;
        }
        [data-testid="stSidebar"] .stElementContainer.st-key-send_otp_button div.stButton > button[kind="secondary"] p,
        [data-testid="stSidebar"] .stElementContainer.st-key-send_otp_button div.stButton > button[kind="secondary"] span {
            color: var(--text) !important;
            font-weight: 800 !important;
        }
        [data-testid="stSidebar"] .stElementContainer.st-key-send_otp_button div.stButton > button[kind="secondary"]:hover {
            background: rgba(30, 41, 59, 0.92) !important;
            border-color: rgba(56, 189, 248, 0.48) !important;
            color: #ffffff !important;
            box-shadow: none !important;
        }

        /* Phase 1 premium UX */
        .hero-chip-label {
            color: var(--muted-2);
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0.11em;
            margin-top: 1rem;
            text-transform: uppercase;
        }
        .hero-workflow-stepper {
            display: grid;
            gap: 0.48rem;
        }
        .hero-workflow-step {
            align-items: center;
            background: rgba(15, 23, 42, 0.58);
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 12px;
            display: flex;
            gap: 0.55rem;
            padding: 0.52rem 0.58rem;
        }
        .hero-workflow-step b,
        .analysis-step b {
            align-items: center;
            background: rgba(56, 189, 248, 0.14);
            border: 1px solid rgba(56, 189, 248, 0.28);
            border-radius: 999px;
            color: #bae6fd;
            display: inline-flex;
            flex: 0 0 1.55rem;
            font-size: 0.74rem;
            height: 1.55rem;
            justify-content: center;
            width: 1.55rem;
        }
        .hero-workflow-step span {
            color: #dbeafe !important;
            font-size: 0.8rem;
            font-weight: 750;
            line-height: 1.2;
        }

        .sidebar-premium-card {
            background:
                linear-gradient(180deg, rgba(15, 23, 42, 0.80), rgba(2, 6, 23, 0.48));
            border: 1px solid rgba(148, 163, 184, 0.18);
            border-radius: 14px;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
            margin: 0.75rem 0 0.55rem;
            padding: 0.82rem;
        }
        .sidebar-premium-card span {
            color: var(--blue) !important;
            display: block;
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0.1em;
            line-height: 1.1;
            text-transform: uppercase;
        }
        .sidebar-premium-card strong {
            color: var(--text) !important;
            display: block;
            font-size: 0.9rem;
            line-height: 1.22;
            margin-top: 0.34rem;
        }
        .sidebar-premium-card p {
            color: var(--muted) !important;
            font-size: 0.78rem !important;
            line-height: 1.42 !important;
            margin: 0.36rem 0 0 !important;
        }
        .sidebar-access-card {
            border-color: rgba(56, 189, 248, 0.24);
        }
        .sidebar-research-card {
            border-color: rgba(34, 197, 94, 0.20);
        }
        .sidebar-quick-card {
            margin-top: 0.9rem;
        }
        /* The sidebar analyze button is now a secondary action, so tone it down. */
        [data-testid="stSidebar"] .stElementContainer.st-key-analyze_button div.stButton > button[kind="secondary"] {
            background: var(--panel-soft) !important;
            border: 1px solid var(--border) !important;
            color: var(--text) !important;
            min-height: 2.35rem !important;
        }
        [data-testid="stSidebar"] .stElementContainer.st-key-analyze_button div.stButton > button[kind="secondary"]:hover {
            background: var(--panel-strong) !important;
            border-color: var(--blue) !important;
            color: #ffffff !important;
        }

        .sample-report-preview {
            background:
                radial-gradient(circle at 82% 10%, rgba(34, 197, 94, 0.12), transparent 16rem),
                linear-gradient(145deg, rgba(15, 23, 42, 0.94), rgba(2, 6, 23, 0.70));
            border: 1px solid rgba(148, 163, 184, 0.20);
            border-radius: var(--radius-xl);
            box-shadow: 0 24px 70px rgba(0, 0, 0, 0.30), inset 0 1px 0 rgba(255, 255, 255, 0.05);
            margin-top: 0.4rem;
            padding: 1.45rem;
        }
        .sample-report-head {
            align-items: flex-start;
            display: flex;
            gap: 1rem;
            justify-content: space-between;
        }
        .sample-kicker,
        .sample-report-grid span,
        .sample-verdict-card span {
            color: var(--muted-2) !important;
            display: block;
            font-size: 0.72rem;
            font-weight: 850;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        .sample-report-head h3 {
            font-size: clamp(1.5rem, 2.6vw, 2.2rem);
            letter-spacing: -0.02em;
            margin: 0.35rem 0 0;
        }
        .sample-report-head p,
        .sample-report-try {
            color: var(--muted) !important;
            margin: 0.45rem 0 0 !important;
        }
        .sample-verdict-card {
            background: linear-gradient(180deg, rgba(22, 163, 74, 0.22), rgba(15, 23, 42, 0.72));
            border: 1px solid rgba(34, 197, 94, 0.34);
            border-radius: 16px;
            min-width: 170px;
            padding: 1rem;
            text-align: right;
        }
        .sample-verdict-card strong {
            color: var(--green) !important;
            display: block;
            font-size: 2rem;
            letter-spacing: 0;
            line-height: 1.05;
            margin-top: 0.25rem;
        }
        .sample-verdict-card small {
            color: #bbf7d0;
            font-weight: 750;
        }
        .sample-report-grid {
            display: grid;
            gap: 0.8rem;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            margin-top: 1rem;
        }
        .sample-report-grid article {
            background: rgba(15, 23, 42, 0.64);
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 14px;
            padding: 0.92rem;
        }
        .sample-report-grid strong {
            color: var(--text);
            display: block;
            font-size: 0.98rem;
            line-height: 1.35;
            margin-top: 0.45rem;
        }
        .sample-report-sections {
            display: flex;
            flex-wrap: wrap;
            gap: 0.46rem;
            margin-top: 1rem;
        }
        .sample-report-section-pill {
            background: rgba(30, 41, 59, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 999px;
            color: #dbeafe !important;
            font-size: 0.74rem;
            font-weight: 750;
            padding: 0.34rem 0.58rem;
        }

        .analysis-progress-shell {
            background: linear-gradient(145deg, rgba(15, 23, 42, 0.94), rgba(2, 6, 23, 0.70));
            border: 1px solid rgba(56, 189, 248, 0.22);
            border-radius: var(--radius-lg);
            box-shadow: 0 18px 50px rgba(0, 0, 0, 0.28), inset 0 1px 0 rgba(255, 255, 255, 0.05);
            margin-bottom: 0.85rem;
            padding: 1rem;
        }
        .analysis-progress-shell > div:first-child span {
            color: var(--blue) !important;
            display: block;
            font-size: 0.7rem;
            font-weight: 850;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        .analysis-progress-shell > div:first-child strong {
            color: var(--text);
            display: block;
            font-size: 1rem;
            margin-top: 0.24rem;
        }
        .analysis-stepper {
            display: grid;
            gap: 0.55rem;
            grid-template-columns: repeat(5, minmax(0, 1fr));
            margin-top: 0.85rem;
        }
        .analysis-step {
            background: rgba(15, 23, 42, 0.58);
            border: 1px solid rgba(148, 163, 184, 0.14);
            border-radius: 12px;
            padding: 0.68rem;
        }
        .analysis-step span {
            color: var(--muted) !important;
            display: block;
            font-size: 0.76rem;
            font-weight: 750;
            line-height: 1.2;
            margin-top: 0.45rem;
        }
        .analysis-step.is-active {
            background: rgba(56, 189, 248, 0.12);
            border-color: rgba(56, 189, 248, 0.42);
        }
        .analysis-step.is-complete b {
            background: rgba(34, 197, 94, 0.18);
            border-color: rgba(34, 197, 94, 0.36);
            color: #bbf7d0;
        }

        .analysis-wit {
            animation: witFadeIn 0.6s ease;
            background: linear-gradient(105deg, rgba(56, 189, 248, 0.08), rgba(129, 140, 248, 0.06));
            border-left: 3px solid rgba(56, 189, 248, 0.42);
            border-radius: 8px;
            color: var(--muted);
            font-size: 0.82rem;
            font-style: italic;
            font-weight: 500;
            letter-spacing: 0.01em;
            margin-top: 0.65rem;
            padding: 0.65rem 0.85rem;
        }
        @keyframes witFadeIn {
            from { opacity: 0; transform: translateY(-4px); }
            to   { opacity: 1; transform: translateY(0); }
        }

        .executive-verdict-strip {
            align-items: stretch;
            background:
                radial-gradient(circle at 12% 0%, rgba(56, 189, 248, 0.16), transparent 15rem),
                linear-gradient(145deg, rgba(15, 23, 42, 0.92), rgba(2, 6, 23, 0.68));
            border: 1px solid rgba(148, 163, 184, 0.20);
            border-radius: var(--radius-lg);
            box-shadow: 0 18px 50px rgba(0, 0, 0, 0.26), inset 0 1px 0 rgba(255, 255, 255, 0.05);
            display: flex;
            gap: 1rem;
            justify-content: space-between;
            margin: 1rem 0 0.6rem;
            padding: 1rem;
        }
        .executive-verdict-copy span {
            color: var(--blue) !important;
            display: block;
            font-size: 0.72rem;
            font-weight: 850;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        .executive-verdict-copy h3 {
            font-size: clamp(1.25rem, 2.1vw, 1.85rem);
            letter-spacing: -0.02em;
            margin: 0.32rem 0 0;
        }
        .executive-verdict-copy p {
            color: var(--muted) !important;
            margin: 0.38rem 0 0 !important;
        }
        .executive-verdict-metrics {
            display: grid;
            gap: 0.65rem;
            grid-template-columns: repeat(4, minmax(110px, 1fr));
            min-width: min(100%, 640px);
        }
        .executive-verdict-metric {
            background: rgba(15, 23, 42, 0.66);
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 14px;
            padding: 0.78rem;
        }
        .executive-verdict-metric span {
            color: var(--muted-2) !important;
            display: block;
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0.08em;
            text-transform: uppercase;
        }
        .executive-verdict-metric strong {
            color: var(--text);
            display: block;
            font-size: 1rem;
            line-height: 1.18;
            margin-top: 0.35rem;
        }

        @media (max-width: 980px) {
            .executive-verdict-strip,
            .sample-report-head {
                flex-direction: column;
            }
            .executive-verdict-metrics,
            .analysis-stepper {
                grid-template-columns: repeat(2, minmax(0, 1fr));
                min-width: 0;
            }
        }
        @media (max-width: 640px) {
            .sample-report-grid,
            .executive-verdict-metrics,
            .analysis-stepper {
                grid-template-columns: 1fr;
            }
            .sample-verdict-card {
                min-width: 0;
                text-align: left;
            }
        }

        /* Phase 1 viewport fit pass: keep the action path visible above the fold. */
        .page-header {
            margin-bottom: 0.72rem !important;
            padding: 1.05rem !important;
        }
        .page-header p {
            font-size: 0.94rem !important;
            line-height: 1.42 !important;
            margin-top: 0.48rem !important;
        }
        .hero-chip-label {
            margin-top: 0.68rem !important;
        }
        .hero-chip-row {
            gap: 0.36rem !important;
            margin-top: 0.45rem !important;
        }
        .hero-aside {
            min-width: 245px !important;
            padding: 0.78rem !important;
        }
        .hero-workflow-stepper {
            grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
            gap: 0.38rem !important;
        }
        .hero-workflow-step {
            gap: 0.38rem !important;
            padding: 0.42rem !important;
        }
        .hero-workflow-step span {
            font-size: 0.72rem !important;
        }
        .hero-workflow-step b,
        .analysis-step b {
            flex-basis: 1.32rem !important;
            height: 1.32rem !important;
            width: 1.32rem !important;
        }
        .sidebar-brand {
            margin-bottom: 0.58rem !important;
            padding: 0.78rem !important;
        }
        .sidebar-brand .logo {
            height: 2rem !important;
            margin-bottom: 0.42rem !important;
            width: 2rem !important;
        }
        .sidebar-brand h2 {
            font-size: 0.98rem !important;
        }
        .sidebar-brand p {
            font-size: 0.76rem !important;
            line-height: 1.34 !important;
        }
        .sidebar-premium-card {
            margin: 0.55rem 0 0.38rem !important;
            padding: 0.62rem !important;
        }
        .sidebar-premium-card strong {
            font-size: 0.82rem !important;
            margin-top: 0.2rem !important;
        }
        .sidebar-premium-card p {
            font-size: 0.72rem !important;
            line-height: 1.28 !important;
            margin-top: 0.2rem !important;
        }
        .sidebar-research-card-compact {
            border-color: rgba(34, 197, 94, 0.28) !important;
        }
        .sample-report-preview {
            margin-top: 0.12rem !important;
            padding: 1rem !important;
        }
        .sample-report-head h3 {
            font-size: clamp(1.22rem, 2vw, 1.72rem) !important;
            margin-top: 0.18rem !important;
        }
        .sample-verdict-card {
            padding: 0.72rem !important;
        }
        .sample-verdict-card strong {
            font-size: 1.55rem !important;
        }
        .sample-report-grid {
            gap: 0.55rem !important;
            margin-top: 0.72rem !important;
        }
        .sample-report-grid article {
            padding: 0.7rem !important;
        }
        .sample-report-grid strong {
            font-size: 0.88rem !important;
        }
        .sample-report-sections {
            gap: 0.34rem !important;
            margin-top: 0.72rem !important;
        }
        .hero-action-strip {
            background: linear-gradient(135deg, rgba(56, 189, 248, 0.14), rgba(34, 197, 94, 0.09));
            border: 1px solid rgba(56, 189, 248, 0.24);
            border-radius: var(--radius-lg);
            box-shadow: 0 14px 38px rgba(0, 0, 0, 0.22), inset 0 1px 0 rgba(255, 255, 255, 0.05);
            margin: 0 0 0.42rem;
            padding: 0.78rem 0.9rem;
        }
        .hero-action-strip span {
            color: var(--blue) !important;
            display: block;
            font-size: 0.68rem;
            font-weight: 850;
            letter-spacing: 0.1em;
            text-transform: uppercase;
        }
        .hero-action-strip strong {
            color: var(--text) !important;
            display: block;
            font-size: 1rem;
            line-height: 1.2;
            margin-top: 0.22rem;
        }
        .hero-action-strip p {
            color: var(--muted) !important;
            font-size: 0.8rem !important;
            line-height: 1.34 !important;
            margin: 0.2rem 0 0 !important;
        }
        .hero-proof-row {
            display: flex;
            flex-wrap: wrap;
            gap: 0.36rem;
            margin-top: 0.55rem;
        }
        .hero-proof-row em {
            background: rgba(15, 23, 42, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.16);
            border-radius: 999px;
            color: #dbeafe;
            font-size: 0.72rem;
            font-style: normal;
            font-weight: 800;
            padding: 0.26rem 0.48rem;
        }
        .stElementContainer.st-key-hero_analyze_button div.stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #22c55e, #38bdf8) !important;
            border-color: rgba(187, 247, 208, 0.78) !important;
            box-shadow: 0 16px 38px rgba(34, 197, 94, 0.28), 0 0 0 4px rgba(56, 189, 248, 0.12) !important;
            color: #03111d !important;
            min-height: 2.7rem !important;
        }
        .stElementContainer.st-key-hero_analyze_button div.stButton > button[kind="primary"] p,
        .stElementContainer.st-key-hero_analyze_button div.stButton > button[kind="primary"] span {
            color: #03111d !important;
            font-weight: 900 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    if is_light:
        st.markdown(
            """
            <style>
            [data-testid="stSidebar"] {
                background: #FAFAFA !important;
                box-shadow: none !important;
            }
            [data-testid="stSidebarContent"] {
                scrollbar-color: rgba(29, 185, 84, 0.42) #E8E8E8 !important;
            }
            [data-testid="stSidebarContent"]::-webkit-scrollbar-track {
                background: #E8E8E8 !important;
            }
            [data-testid="stSidebarContent"]::-webkit-scrollbar-thumb {
                background: rgba(29, 185, 84, 0.42) !important;
            }
            .sidebar-brand {
                background: linear-gradient(135deg, #F5F5F5, #FFFFFF) !important;
                border-color: #E8E8E8 !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
            }
            .sidebar-brand .logo {
                background: linear-gradient(135deg, #1DB954, #1ED760) !important;
                border-color: rgba(29, 185, 84, 0.20) !important;
                box-shadow: 0 8px 20px rgba(29, 185, 84, 0.16) !important;
                color: #FFFFFF !important;
                text-shadow: none !important;
            }
            .hero-card {
                background: #FFFFFF !important;
                border-color: #E8E8E8 !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
            }
            .hero-action-strip {
                background: linear-gradient(135deg, rgba(29, 185, 84, 0.10), rgba(29, 185, 84, 0.05)) !important;
                border-color: rgba(29, 185, 84, 0.18) !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
            }
            .sample-report-preview {
                background: linear-gradient(135deg, #FFFFFF, #F5F5F5) !important;
                border-color: #E8E8E8 !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
            }
            .sample-verdict-card {
                background: linear-gradient(180deg, rgba(29, 185, 84, 0.15), rgba(245, 245, 245, 0.8)) !important;
                border-color: rgba(29, 185, 84, 0.24) !important;
            }
            .empty-state,
            .empty-preview-card {
                background: linear-gradient(180deg, #FFFFFF, #F5F5F5) !important;
                border-color: #E8E8E8 !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
            }
            .empty-state-icon {
                background: rgba(29, 185, 84, 0.10) !important;
                border-color: rgba(29, 185, 84, 0.20) !important;
                box-shadow: 0 0 0 8px rgba(29, 185, 84, 0.05) !important;
            }
            .sidebar-premium-card {
                background: linear-gradient(180deg, #FFFFFF, #F5F5F5) !important;
                border-color: #E8E8E8 !important;
                box-shadow: none !important;
            }
            .analysis-progress-shell {
                background: linear-gradient(135deg, #FFFFFF, #F5F5F5) !important;
                border-color: #E8E8E8 !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
            }
            .analysis-step,
            .executive-verdict-metric,
            .hero-proof-row em,
            .hero-workflow-step,
            .sample-report-grid article,
            .sample-report-section-pill,
            .sample-verdict-card small {
                background: #F5F5F5 !important;
                border-color: #E8E8E8 !important;
                color: #4A4A4A !important;
            }
            .analysis-wit {
                background: linear-gradient(105deg, rgba(29, 185, 84, 0.08), rgba(29, 185, 84, 0.04)) !important;
                border-left-color: rgba(29, 185, 84, 0.42) !important;
            }
            .executive-verdict-strip {
                background: linear-gradient(135deg, #FFFFFF, #F5F5F5) !important;
                border-color: #E8E8E8 !important;
                box-shadow: 0 1px 3px rgba(0, 0, 0, 0.06) !important;
            }
            .stElementContainer.st-key-hero_analyze_button div.stButton > button[kind="primary"] {
                background: linear-gradient(135deg, #1DB954, #1ED760) !important;
                border-color: #1DB954 !important;
                box-shadow: 0 10px 24px rgba(29, 185, 84, 0.20) !important;
                color: #FFFFFF !important;
            }
            .stElementContainer.st-key-hero_analyze_button div.stButton > button[kind="primary"] p,
            .stElementContainer.st-key-hero_analyze_button div.stButton > button[kind="primary"] span {
                color: #FFFFFF !important;
            }
            .stTextInput input,
            [data-testid="stSidebar"] .stTextInput input,
            [data-testid="stSidebar"] [data-baseweb="input"] input {
                background: #FFFFFF !important;
                border-color: #E8E8E8 !important;
                color: #1A1A1A !important;
            }
            [data-testid="stSidebar"] [data-testid="stAlert"] {
                background: #F5F5F5 !important;
                border-color: #E8E8E8 !important;
                box-shadow: none !important;
                color: #1A1A1A !important;
            }
            [data-testid="stSidebar"] [data-testid="stAlert"] p,
            [data-testid="stSidebar"] [data-testid="stAlert"] div {
                color: #1A1A1A !important;
            }
            .footer {
                background: #F5F5F5 !important;
                border-color: #E8E8E8 !important;
            }
            [data-testid="stSidebar"] .stElementContainer.st-key-analyze_button div.stButton > button[kind="secondary"],
            [data-testid="stSidebar"] .stElementContainer.st-key-send_otp_button div.stButton > button[kind="secondary"],
            [data-testid="stSidebar"] .st-key-send_otp_button button,
            [data-testid="stSidebar"] div[data-testid="stButton"][class*="send_otp_button"] button,
            [data-testid="stSidebar"] button[aria-label="Send OTP"],
            [data-testid="stSidebar"] div.stButton > button,
            [data-testid="stSidebar"] button[kind="primary"] {
                background: #FFFFFF !important;
                border-color: #E8E8E8 !important;
                color: #1A1A1A !important;
            }
            [data-testid="stSidebar"] .stElementContainer.st-key-analyze_button div.stButton > button[kind="secondary"]:hover,
            [data-testid="stSidebar"] .stElementContainer.st-key-send_otp_button div.stButton > button[kind="secondary"]:hover,
            [data-testid="stSidebar"] .st-key-send_otp_button button:hover,
            [data-testid="stSidebar"] div[data-testid="stButton"][class*="send_otp_button"] button:hover,
            [data-testid="stSidebar"] button[aria-label="Send OTP"]:hover,
            [data-testid="stSidebar"] div.stButton > button:hover,
            [data-testid="stSidebar"] button[kind="primary"]:hover {
                background: #F5F5F5 !important;
                border-color: #1DB954 !important;
                color: #1A1A1A !important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
    _inject_mobile_styles()
    _inject_mobile_sidebar_close_js()


def _inject_mobile_styles() -> None:
    """Mobile UX overhaul — overlay drawer, 16px padding, 14px font floor, 44px tap targets."""
    st.markdown(
        """
        <style>
        /* ============================================
           MOBILE UX OVERHAUL — Stock Research Assistant
           Based on Claude Opus audit + Chrome DevTools measurements
           ============================================ */

        @media (max-width: 768px) {

            /* ---------- 1. SIDEBAR: FULL OVERLAY DRAWER ---------- */
            [data-testid="stSidebar"] {
                position: fixed !important;
                top: 0 !important;
                left: 0 !important;
                bottom: 0 !important;
                height: 100dvh !important;
                width: 85vw !important;
                max-width: 320px !important;
                min-width: 280px !important;
                z-index: 9999 !important;
                transform: translateX(-100%) !important;
                transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
                box-shadow: none !important;
            }

            [data-testid="stSidebar"][aria-expanded="true"] {
                transform: translateX(0) !important;
                box-shadow: 4px 0 24px rgba(0, 0, 0, 0.3) !important;
            }

            /* Kill the collapse-control rail sliver */
            [data-testid="stSidebar"] > div:first-child {
                width: 100% !important;
            }

            /* Scrim / backdrop — tappable area behind sidebar */
            .stApp::after {
                content: "" !important;
                display: block !important;
                position: fixed !important;
                inset: 0 !important;
                background: rgba(0, 0, 0, 0.5) !important;
                z-index: 9998 !important;
                opacity: 0 !important;
                visibility: hidden !important;
                transition: opacity 0.3s ease, visibility 0.3s ease !important;
                pointer-events: none !important;
                -webkit-tap-highlight-color: transparent !important;
            }

            /* Show scrim when sidebar is open */
            .stApp:has([data-testid="stSidebar"][aria-expanded="true"])::after {
                opacity: 1 !important;
                visibility: visible !important;
                pointer-events: auto !important;
                cursor: pointer !important;
            }

            /* Enlarge the close button — make it obvious */
            [data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarCollapseButton"] {
                position: absolute !important;
                top: 8px !important;
                right: 8px !important;
                z-index: 10001 !important;
            }

            [data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarCollapseButton"] button {
                width: 48px !important;
                height: 48px !important;
                min-height: 48px !important;
                border-radius: 12px !important;
                background: rgba(255, 255, 255, 0.1) !important;
                border: 1px solid rgba(0, 0, 0, 0.1) !important;
                backdrop-filter: blur(8px) !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                transition: background 0.2s ease !important;
            }

            [data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarCollapseButton"] button:hover,
            [data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarCollapseButton"] button:active {
                background: rgba(0, 0, 0, 0.1) !important;
            }

            [data-testid="stSidebar"][aria-expanded="true"] [data-testid="stSidebarCollapseButton"] button svg {
                width: 24px !important;
                height: 24px !important;
            }

            /* Sidebar expand button — proper FAB when sidebar is closed */
            [data-testid="stExpandSidebarButton"] {
                position: fixed !important;
                top: 0.75rem !important;
                left: 0.75rem !important;
                z-index: 10000 !important;
                width: 44px !important;
                height: 44px !important;
                min-height: 44px !important;
                min-width: 44px !important;
                display: flex !important;
                align-items: center !important;
                justify-content: center !important;
                border-radius: 12px !important;
                border: 1px solid var(--border, #E8E8E8) !important;
                background: var(--panel, #FFFFFF) !important;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12) !important;
            }
            [data-testid="stExpandSidebarButton"] svg {
                width: 22px !important;
                height: 22px !important;
            }

            /* Main content reclaims full width — NO offset for rail */
            [data-testid="stAppViewContainer"],
            [data-testid="stAppViewContainer"] .block-container,
            [data-testid="stAppViewContainer"] > section {
                margin-left: 0 !important;
                padding-left: 0 !important;
                max-width: 100% !important;
                width: 100% !important;
            }

            /* ---------- 2. MAIN CONTENT PADDING ---------- */
            [data-testid="stAppViewContainer"] .block-container {
                padding: 1rem 1rem 4rem 1rem !important;
                max-width: 100% !important;
                box-sizing: border-box !important;
            }

            [data-testid="stAppViewContainer"] > section {
                padding-top: 0.5rem !important;
            }

            [data-testid="stVerticalBlock"] {
                gap: 0.75rem !important;
            }

            /* ---------- 3. FONT SIZE FLOOR (WCAG 14px minimum) ---------- */
            /* Use hard 14px override — max() doesn't beat Streamlit's !important */
            [data-testid="stAppViewContainer"] .block-container p,
            [data-testid="stAppViewContainer"] .block-container span,
            [data-testid="stAppViewContainer"] .block-container label,
            [data-testid="stAppViewContainer"] .block-container [data-testid="stWidgetLabel"],
            [data-testid="stAppViewContainer"] .block-container [data-testid="stWidgetLabel"] label,
            [data-testid="stAppViewContainer"] .block-container [data-testid="stMarkdown"] p,
            [data-testid="stAppViewContainer"] .block-container [data-testid="stMarkdown"] span,
            [data-testid="stAppViewContainer"] .block-container small,
            [data-testid="stAppViewContainer"] .block-container [data-testid="stCaptionContainer"],
            [data-testid="stAppViewContainer"] .block-container [data-testid="stCaptionContainer"] p {
                font-size: 0.875rem !important;
                line-height: 1.4 !important;
            }

            /* Headings — mobile-appropriate sizes */
            [data-testid="stAppViewContainer"] h1 { font-size: 1.5rem !important; }
            [data-testid="stAppViewContainer"] h2 { font-size: 1.25rem !important; }
            [data-testid="stAppViewContainer"] h3 { font-size: 1.125rem !important; }

            /* Section labels that measured 10.88px — force 14px */
            [data-testid="stSidebar"] [data-testid="stMarkdown"] span,
            [data-testid="stSidebar"] [data-testid="stMarkdown"] p,
            [data-testid="stSidebar"] label,
            [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {
                font-size: 0.875rem !important;
            }

            /* ---------- 4. TAP TARGETS (44px minimum) ---------- */
            [data-testid="stAppViewContainer"] .block-container a,
            [data-testid="stAppViewContainer"] .block-container button,
            [data-testid="stAppViewContainer"] .block-container [role="button"],
            [data-testid="stAppViewContainer"] .block-container select,
            [data-testid="stAppViewContainer"] .block-container input,
            [data-testid="stAppViewContainer"] .block-container [data-testid="baseButton-secondary"],
            [data-testid="stAppViewContainer"] .block-container [data-testid="baseButton-primary"] {
                min-height: 44px !important;
                min-width: 44px !important;
                display: inline-flex !important;
                align-items: center !important;
                padding: 0.5rem 0.75rem !important;
                box-sizing: border-box !important;
            }

            /* Email link (measured 161x18) */
            [data-testid="stAppViewContainer"] .block-container a[href^="mailto:"] {
                min-height: 44px !important;
                padding: 0.75rem 0 !important;
                display: inline-flex !important;
                align-items: center !important;
            }

            /* Heading anchor links (measured 16x16) */
            [data-testid="stAppViewContainer"] .block-container a[href^="#"],
            [data-testid="stAppViewContainer"] .block-container .header-anchor {
                min-height: 44px !important;
                min-width: 44px !important;
                display: inline-flex !important;
                align-items: center !important;
                justify-content: center !important;
                margin: -12px !important;
                padding: 12px !important;
            }

            /* Tab buttons */
            [data-testid="stTabs"] [role="tablist"] {
                flex-wrap: wrap !important;
            }
            [data-testid="stTabs"] [role="tab"] {
                flex: 1 1 auto !important;
                font-size: 0.875rem !important;
                min-height: 44px !important;
                padding: 0.5rem 0.75rem !important;
            }

            /* ---------- 5. COLUMNS → STACK ---------- */
            [data-testid="stHorizontalBlock"],
            .stHorizontalBlock {
                flex-direction: column !important;
                flex-wrap: nowrap !important;
                gap: 0.75rem !important;
            }

            [data-testid="stHorizontalBlock"] > [data-testid="column"],
            [data-testid="stHorizontalBlock"] > [data-testid="stVerticalBlock"],
            [data-testid="stHorizontalBlock"] > div,
            .stHorizontalBlock > div {
                flex: 0 0 100% !important;
                width: 100% !important;
                max-width: 100% !important;
                min-width: 0 !important;
            }

            /* ---------- 6. HERO / PAGE HEADER ---------- */
            .page-header {
                flex-direction: column !important;
                padding: 1rem !important;
                margin-bottom: 0.75rem !important;
            }
            .page-header h1 {
                font-size: 1.5rem !important;
                line-height: 1.15 !important;
                hyphens: none !important;
                word-break: normal !important;
            }
            .page-header p {
                font-size: 0.92rem !important;
            }
            .hero-chip-row {
                gap: 0.4rem !important;
            }
            .hero-chip-row span {
                font-size: 0.875rem !important;
                padding: 0.25rem 0.5rem !important;
            }
            .hero-aside {
                min-width: auto !important;
                width: 100% !important;
                margin-top: 0.75rem !important;
            }

            /* ---------- 7. STOCK HEADER ---------- */
            .stock-title-row {
                flex-direction: column !important;
                align-items: flex-start !important;
                gap: 0.75rem !important;
            }
            .stock-price-block {
                min-width: auto !important;
                text-align: left !important;
                width: 100% !important;
            }
            .stock-price {
                font-size: 1.65rem !important;
            }

            /* ---------- 8. SAMPLE REPORT PREVIEW ---------- */
            .sample-report-preview {
                padding: 1rem !important;
            }
            .sample-report-head {
                flex-direction: column !important;
                gap: 1rem !important;
            }
            .sample-report-head h3 {
                font-size: 1.1rem !important;
            }
            .sample-verdict-card {
                width: 100% !important;
                min-width: auto !important;
                text-align: center !important;
                padding: 0.75rem !important;
            }
            .sample-report-grid {
                grid-template-columns: 1fr !important;
                gap: 0.6rem !important;
            }

            /* ---------- 9. EXECUTIVE VERDICT STRIP ---------- */
            .executive-verdict-strip {
                flex-direction: column !important;
                padding: 1rem !important;
            }
            .executive-verdict-copy h3 {
                font-size: 1.1rem !important;
            }
            .executive-verdict-metrics {
                grid-template-columns: repeat(2, 1fr) !important;
                gap: 0.5rem !important;
                margin-top: 1rem !important;
            }
            .executive-verdict-metric {
                padding: 0.55rem !important;
            }

            /* ---------- 10. KPI / SCORE CARDS ---------- */
            .score-card, [data-testid="stMetric"] {
                min-height: auto !important;
            }
            .section-title {
                font-size: 0.95rem !important;
            }
            .section-title-wrap {
                margin: 1rem 0 0.5rem !important;
            }

            /* ---------- 11. DATA TABLES ---------- */
            [data-testid="stDataFrame"],
            [data-testid="stTable"],
            .stDataFrame {
                overflow-x: auto !important;
                -webkit-overflow-scrolling: touch !important;
                max-width: 100% !important;
                border-radius: 8px !important;
            }
            [data-testid="stDataFrame"] td,
            [data-testid="stDataFrame"] th {
                white-space: nowrap !important;
                font-size: 0.8125rem !important;
                padding: 0.5rem 0.625rem !important;
            }

            /* ---------- 12. CHARTS / PLOTS ---------- */
            [data-testid="stAppViewContainer"] .block-container [data-testid="stPlotlyChart"],
            [data-testid="stAppViewContainer"] .block-container [data-testid="stVegaLiteChart"],
            [data-testid="stAppViewContainer"] .block-container .stPlotlyChart {
                overflow-x: auto !important;
                -webkit-overflow-scrolling: touch !important;
                max-width: 100% !important;
            }

            /* ---------- 13. EXPANDERS ---------- */
            [data-testid="stExpander"] summary {
                min-height: 48px !important;
                padding: 0.75rem 1rem !important;
                font-size: 0.9375rem !important;
                display: flex !important;
                align-items: center !important;
            }

            /* ---------- 14. FOOTER ---------- */
            .footer {
                font-size: 0.8125rem !important;
                padding: 0.75rem 1rem !important;
            }

            /* ---------- 15. MOBILE MENU BUTTON ---------- */
            .mobile-menu-btn {
                align-items: center;
                background: var(--panel, #F5F5F5);
                border: 1px solid var(--border, #E8E8E8);
                border-radius: 10px;
                box-shadow: var(--shadow);
                color: var(--text, #1A1A1A);
                cursor: pointer;
                display: flex !important;
                height: 2.75rem;
                justify-content: center;
                left: 0.6rem;
                position: fixed;
                top: 0.6rem;
                width: 2.75rem;
                z-index: 999999;
            }
            .mobile-menu-btn svg {
                fill: currentColor;
                height: 1.25rem;
                width: 1.25rem;
            }
        }

        /* ---------- EXTRA-TIGHT SCREENS (<=380px, iPhone SE) ---------- */
        @media (max-width: 380px) {
            [data-testid="stAppViewContainer"] .block-container {
                padding: 0.75rem 0.75rem 4rem 0.75rem !important;
            }

            [data-testid="stSidebar"] {
                width: 90vw !important;
            }

            [data-testid="stAppViewContainer"] h1 { font-size: 1.375rem !important; }
            [data-testid="stAppViewContainer"] h2 { font-size: 1.125rem !important; }

            .executive-verdict-metrics {
                grid-template-columns: 1fr !important;
            }

            /* Stack tab buttons vertically on very small screens */
            [data-baseweb="tab-list"] {
                flex-direction: column !important;
            }
            [data-baseweb="tab-list"] button {
                width: 100% !important;
            }
        }

        /* Mobile menu button (hidden on desktop, flex on mobile) */
        .mobile-menu-btn {
            align-items: center;
            background: var(--panel, #F5F5F5);
            border: 1px solid var(--border, #E8E8E8);
            border-radius: 10px;
            box-shadow: var(--shadow);
            color: var(--text, #1A1A1A);
            cursor: pointer;
            display: none;
            height: 2.75rem;
            justify-content: center;
            left: 0.6rem;
            position: fixed;
            top: 0.6rem;
            width: 2.75rem;
            z-index: 999999;
        }
        .mobile-menu-btn svg {
            fill: currentColor;
            height: 1.25rem;
            width: 1.25rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _inject_mobile_sidebar_close_js() -> None:
    """JS to close sidebar when tapping outside it (on the scrim)."""
    try:
        import streamlit.components.v1 as components
        components.html(
            """
<script>
(function() {
  function setupScrimClose() {
    const app = document.querySelector('.stApp') || document.querySelector('[data-testid="stAppViewContainer"]');
    const sidebar = document.querySelector('[data-testid="stSidebar"]');
    if (!app || !sidebar) {
      setTimeout(setupScrimClose, 500);
      return;
    }
    app.addEventListener('click', function(e) {
      if (sidebar.getAttribute('aria-expanded') !== 'true') return;
      const sidebarRect = sidebar.getBoundingClientRect();
      // Click is outside the sidebar bounds = on the scrim
      if (e.clientX > sidebarRect.right || e.clientX < sidebarRect.left) {
        const collapseBtn = sidebar.querySelector(
          '[data-testid="stSidebarCollapseButton"] button'
        );
        if (collapseBtn) collapseBtn.click();
      }
    }, { capture: true });
  }
  // Wait for Streamlit to fully render
  setTimeout(setupScrimClose, 1000);
  // Also re-setup on Streamlit reruns
  if (document.body) {
    const observer = new MutationObserver(function() {
      clearTimeout(window._scrimTimer);
      window._scrimTimer = setTimeout(setupScrimClose, 500);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }
})();
</script>
""",
            height=0,
        )
    except Exception:
        pass


def init_state() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    defaults = {
        "sra_market_data": None,
        "sra_result": None,
        "sra_report_history": [],
        "_history_email": "",
        "symbol_input": "SBIN",
        "user_email": "",
        "_auth_verified": False,
        "_otp_sent": False,
        "_otp_email": "",
        "_session_report_count": 0,
        "_free_account_claimed": False,
        "theme": "light",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if "sra_deep_research" not in st.session_state:
        st.session_state["sra_deep_research"] = {}
    load_history_from_disk()


def get_deepseek_key() -> str:
    try:
        value = st.secrets["DEEPSEEK_API_KEY"]
        if value:
            return str(value).strip()
    except Exception:
        return os.getenv("DEEPSEEK_API_KEY", "").strip()
    return os.getenv("DEEPSEEK_API_KEY", "").strip()

def _clean_email(email: str) -> str:
    return (email or "").strip().lower()


def render_sidebar_access(interactive: bool = True) -> str:
    """Render access / auth UI.

    When *interactive* is ``True`` (default), the full email → OTP → verify
    flow is rendered (used in the **main content area** via ``render_auth_gate``).

    When *interactive* is ``False``, only the verified-state badge and plan
    info are shown (used inside the **sidebar** for authenticated users).

    Verified state is guarded so that clicking the main "Generate Report" button
    (or any other sidebar interaction) does not accidentally reset authentication.
    """
    if not REQUIRE_AUTH:
        st.session_state.user_email = "beta-user@sra.local"
        st.session_state["_auth_verified"] = True
        st.success("Free during beta")
        st.caption("No login required - open access")
        return "beta-user@sra.local"

    if "user_email" not in st.session_state:
        st.session_state.user_email = ""
    if "_auth_verified" not in st.session_state:
        st.session_state["_auth_verified"] = False
    if "_otp_sent" not in st.session_state:
        st.session_state["_otp_sent"] = False
    if "_otp_email" not in st.session_state:
        st.session_state["_otp_email"] = ""

    # ── 1. Restore persisted auth once per session ──
    if not st.session_state.get("_auth_verified") and not st.session_state.get("user_email"):
        persisted_email = load_auth()
        if persisted_email and get_user(persisted_email):
            st.session_state["_auth_verified"] = True
            st.session_state.user_email = persisted_email
            st.session_state["_otp_email"] = persisted_email

    # ── 2. Already verified → show badge only ──
    verified_email = _clean_email(st.session_state.user_email)
    if is_authenticated() and verified_email:
        st.success(f"Verified as {verified_email}")
        return verified_email

    # ── Non-interactive mode: nothing more to render ──
    if not interactive:
        st.caption("Free during beta" if not REQUIRE_AUTH else "Sign in from the main page to start analysing stocks.")
        return st.session_state.user_email if is_authenticated() else ""

    # ── 3. Offline / dev-mode bypass ──
    if _supabase_offline():
        email = st.text_input(
            "Email",
            value=st.session_state.get("_otp_email", ""),
            placeholder="you@company.com",
            key="_email_input",
            help="Used to verify access, check your plan, and track report usage.",
        )
        clean_email = _clean_email(email)
        st.session_state["_otp_email"] = clean_email
        st.session_state.user_email = clean_email
        st.session_state["_auth_verified"] = bool(clean_email)
        if clean_email:
            save_auth(clean_email)
            st.success(f"Verified as {clean_email}")
        st.caption("Dev mode: Supabase Auth is not configured, using session-only access.")
        return st.session_state.user_email

    # ── 4. Email input (sync widget state carefully) ──
    email = st.text_input(
        "Email",
        value=st.session_state.get("_otp_email", ""),
        placeholder="you@company.com",
        key="_email_input",
        help="Used to verify access, check your plan, and track report usage.",
    )
    clean_email = _clean_email(email)

    # Only reset OTP flow when the user *intentionally* changes the email address.
    # If the input is momentarily empty during a fast rerun, do not wipe verified state.
    if clean_email and clean_email != st.session_state.get("_otp_email", ""):
        st.session_state["_otp_email"] = clean_email
        st.session_state["_otp_sent"] = False
        st.session_state["_auth_verified"] = False
        st.session_state.user_email = ""
        clear_auth()

    # ── 5. Send OTP ──
    if st.button(
        "Send OTP",
        key="send_otp_button",
        use_container_width=True,
        type="secondary",
    ):
        if not clean_email:
            st.warning("Please enter your email address first.")
        elif "@" not in clean_email or "." not in clean_email.split("@")[-1]:
            st.warning("Please enter a valid email address (e.g. you@company.com).")
        elif send_otp(clean_email):
            st.session_state["_otp_sent"] = True
            st.session_state["_otp_email"] = clean_email
            st.success("OTP sent. Check your email.")
        else:
            st.error("Could not send OTP. Check Supabase Auth settings and secrets.")

    # ── 6. Verify OTP ──
    if st.session_state.get("_otp_sent") and st.session_state.get("_otp_email") == clean_email:
        token = st.text_input(
            "OTP",
            value="",
            max_chars=8,
            key="_otp_input",
            help="Enter the 6-8 digit code from your email. Copy and paste is supported.",
        )
        if st.button(
            "Verify",
            key="verify_otp_button",
            use_container_width=True,
            type="secondary",
        ):
            auth_response = verify_otp(clean_email, token)
            if auth_response:
                st.session_state["_supabase_session"] = getattr(auth_response, "session", None)
                st.session_state["_auth_verified"] = True
                st.session_state.user_email = clean_email
                st.session_state["_otp_sent"] = False
                save_auth(clean_email)
                _ensure_user_row(clean_email, _auth_user_id(auth_response))
                st.success(f"Verified as {clean_email}")
                st.rerun()
            else:
                st.error("Invalid or expired OTP.")

    st.caption("Email verification is required before running stock analysis.")
    return st.session_state.user_email if is_authenticated() else ""


def render_auth_gate() -> str:
    """Render the auth flow in the **main content area** when not authenticated.

    This replaces the old sidebar-based auth for mobile friendliness.
    Returns the verified email string (empty if not yet authenticated).
    """
    if not REQUIRE_AUTH:
        st.session_state.user_email = "beta-user@sra.local"
        st.session_state["_auth_verified"] = True
        return "beta-user@sra.local"

    # Fast-path: already authenticated → show badge and return
    verified_email = _clean_email(st.session_state.get("user_email", ""))
    if is_authenticated() and verified_email:
        from payment import get_user, TIER_LIMITS
        user = get_user(verified_email)
        plan = user.get("plan", "free") if isinstance(user, dict) else getattr(user, "plan", "free")
        used = user.get("analyses_used", 0) if isinstance(user, dict) else st.session_state.get("_session_report_count", 0)
        limit = user.get("analyses_limit", TIER_LIMITS["free"]) if isinstance(user, dict) else TIER_LIMITS["free"]
        st.success(f"✓ Verified as {verified_email}")
        st.caption("Free during beta" if not REQUIRE_AUTH else f"{plan.upper()} plan · {used}/{limit} analyses used")
        return verified_email

    st.markdown(
        """
        <div style="max-width:480px; margin:2rem auto; padding:1.5rem 2rem;
                    border-radius:16px;
                    background:var(--card-bg, rgba(255,255,255,0.06));
                    border:1px solid var(--border, rgba(255,255,255,0.08));
                    box-shadow:0 4px 24px rgba(0,0,0,0.10);">
            <h3 style="margin:0 0 0.25rem; font-size:1.25rem;">🔐 Sign in to continue</h3>
            <p style="margin:0 0 1rem; opacity:0.7; font-size:0.92rem;">
                Verify your email to unlock AI-powered stock research reports.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container():
        email = render_sidebar_access(interactive=True)
    return email


def render_research_setup() -> str:
    """Render company picker + quick-pick buttons in the **main content area**.

    Only shown when the user IS authenticated.  Returns the current symbol
    string from session_state so callers can feed it to render_hero_action().
    """
    # Not authenticated → nothing to render; return whatever is in session_state.
    verified_email = _clean_email(st.session_state.get("user_email", ""))
    if not (is_authenticated() and verified_email):
        return st.session_state.get("symbol_input", "SBIN")

    # ── Research setup card ──
    st.markdown(
        """
        <div class="sidebar-premium-card sidebar-research-card sidebar-research-card-compact"
             style="max-width:640px;">
            <span>Research setup</span>
            <strong>Choose an NSE company</strong>
            <p>Company name or ticker — we resolve it before the report runs.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if "symbol_input" not in st.session_state:
        st.session_state.symbol_input = "SBIN"

    symbol = st.text_input(
        "Company or ticker",
        key="symbol_input",
        placeholder="Infosys, SBIN, RELIANCE...",
        help="Enter a company name or NSE ticker. The app resolves names and appends .NS when required.",
        label_visibility="collapsed",
    ).strip()

    if symbol and len(symbol) >= 2:
        suggestions = suggest_tickers(symbol, limit=3)
        resolved_preview = resolve_ticker(symbol)
        if not resolved_preview.get("symbol") and suggestions:
            st.caption(
                "Did you mean: "
                + ", ".join(f"{item['symbol'].replace('.NS', '')} ({item['name']})" for item in suggestions)
            )

    # ── Quick-pick row (horizontal on desktop, scrollable on mobile) ──
    qp_cols = st.columns(len(QUICK_PICKS))
    for col, (quick_symbol, name) in zip(qp_cols, QUICK_PICKS.items()):
        with col:
            st.button(
                f"{quick_symbol} · {name}",
                key=f"quick_{quick_symbol}",
                on_click=lambda s=quick_symbol: st.session_state.__setitem__("symbol_input", s),
                use_container_width=True,
            )

    return symbol


def render_sidebar_sign_out() -> None:
    verified_email = _clean_email(st.session_state.get("user_email", ""))
    if not (is_authenticated() and verified_email):
        return

    st.divider()
    st.button("Sign out", key="supabase_sign_out", use_container_width=True, on_click=_do_sign_out)


def _do_sign_out() -> None:
    """Shared sign-out logic called by both sidebar and main-area sign-out buttons."""
    st.session_state.user_email = ""
    st.session_state["_auth_verified"] = False
    for key in ("_auth_verified", "_supabase_session", "_otp_sent", "_otp_email", "_email_input", "_otp_input"):
        st.session_state.pop(key, None)
    clear_auth()
    client = get_supabase_client()
    if client is not None:
        try:
            client.auth.sign_out()
        except Exception:
            pass


def render_main_sign_out() -> None:
    """Render a sign-out button in the **main content area** (below footer).

    Uses a different widget key than the sidebar sign-out to avoid
    Streamlit's DuplicateWidgetID error.
    """
    verified_email = _clean_email(st.session_state.get("user_email", ""))
    if not (is_authenticated() and verified_email):
        return

    st.markdown("---")
    st.button("Sign out", key="main_sign_out", use_container_width=True, on_click=_do_sign_out)


def _theme_toggle_callback() -> None:
    """Swap light/dark theme — runs BEFORE widget rendering."""
    current = st.session_state.get("theme", "light")
    st.session_state.theme = "light" if current == "dark" else "dark"


def render_sidebar() -> tuple[str, str]:
    """Sidebar with secondary controls: Brand → Access badge → History → Help.

    The company picker and quick-pick buttons have been moved to the main
    content area (``render_research_setup``) so that the core user flow
    works without opening the sidebar on mobile devices.
    """
    with st.sidebar:
        # ── 0. Theme toggle ──
        current_theme = st.session_state.get("theme", "light")
        theme_label = "🌙 Dark" if current_theme == "dark" else "☀️ Light"
        if st.button(
            f"Switch theme ({theme_label})",
            key="theme_toggle",
            use_container_width=True,
            type="secondary",
            on_click=_theme_toggle_callback,
        ):
            pass  # handled by callback, auto-reruns

        # ── 1. Brand ──
        st.markdown(
            f"""
            <div class="sidebar-brand">
                <div class="logo">📊</div>
                <h2>{APP_TITLE}</h2>
                <p>AI-assisted NSE stock research with clean scorecards and a coordinated verdict.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        email = _clean_email(st.session_state.get("user_email", ""))
        current_history_email = email
        if st.session_state.get("_history_email", "") != current_history_email:
            load_history_from_disk()

        # History + Help
        if st.session_state.sra_report_history:
            st.divider()
            st.markdown(
                """
                <div class="sidebar-premium-card sidebar-history-card">
                    <span>Recent analyses</span>
                    <strong>Session history</strong>
                </div>
                """,
                unsafe_allow_html=True,
            )
            for item in st.session_state.sra_report_history[:HISTORY_DISPLAY_LIMIT]:
                symbol_text = str(item.get("symbol") or "Stock")
                verdict_text = str(item.get("verdict") or "Unavailable")
                timestamp = str(item.get("timestamp") or "")
                score = float(item.get("score") or 0)
                row_cols = st.columns([0.82, 0.18], gap="small")
                with row_cols[0]:
                    if st.button(
                        f"{symbol_text} · {verdict_text}  {score:.1f}/10 · {item.get('time', '')}",
                        key=f"hist_btn_{symbol_text}_{timestamp}",
                        use_container_width=True,
                    ):
                        if load_report(symbol_text, timestamp):
                            st.rerun()
                        st.warning("Saved report could not be loaded.")
                with row_cols[1]:
                    payload = report_payload_from_history(item)
                    if payload:
                        report_bytes, report_filename, report_mime = payload
                        st.download_button(
                            "📥",
                            data=report_bytes,
                            file_name=report_filename,
                            mime=report_mime,
                            key=f"hist_dl_{symbol_text}_{timestamp}",
                            use_container_width=True,
                            help="Download saved report",
                        )

        st.markdown(
            (
                """
            <div class="sidebar-help-card">
                <p><strong>Access:</strong> Free during beta.</p>
            </div>
            """
                if not REQUIRE_AUTH
                else """
            <div class="sidebar-help-card">
                <p><strong>Plan & help:</strong> Free access includes quick reports. Upgrade unlocks Deep Research, peer comparison, valuation, governance, and enhanced PDFs.</p>
            </div>
            """
            ),
            unsafe_allow_html=True,
        )
    # Symbol is now captured in the main content area via render_research_setup();
    # read it from session_state so the (email, symbol) return contract is honoured.
    symbol = st.session_state.get("symbol_input", "SBIN").strip()
    return email, symbol


def build_report_pdf(data: dict[str, Any], result: dict[str, Any], pdf_class: Any) -> bytes:
    """Build a branded, McKinsey-style multi-page PDF report."""

    def safe_text(value: Any, max_len: int | None = None) -> str:
        text = "" if value is None else str(value)
        text = (
            text.replace("₹", "Rs.")
            .replace("—", "-")
            .replace("–", "-")
            .replace("’", "'")
            .replace("“", '"')
            .replace("”", '"')
            .replace("×", "x")
        )
        text = text.encode("latin-1", "replace").decode("latin-1")
        return text[:max_len] + "..." if max_len and len(text) > max_len else text

    from datetime import date

    NAVY = (18, 28, 46)
    SLATE = (51, 65, 85)
    CHARCOAL = (31, 41, 55)
    GREY_MID = (107, 114, 128)
    GREY_LIGHT = (248, 250, 252)
    WHITE = (255, 255, 255)
    LINE = (200, 205, 211)

    scores = {
        name: get_agent_output(result, data, name).score
        for name in SCORE_ORDER
    }
    generated_at = str(result.get("generated_at", data.get("as_of", "")))
    report_date = generated_at or date.today().strftime("%d %B %Y")
    verdict = str(result.get("verdict", "Unavailable"))
    symbol = str(data.get("symbol", ""))
    name = str(data.get("name", symbol or "Stock Report"))
    composite = float(result.get("composite", 0) or 0)

    summary = re.sub(r"[*_`#>]+", "", str(result.get("final_report", "")))
    summary = re.sub(r"\n{3,}", "\n\n", summary).strip()
    if len(summary) > 1600:
        summary = f"{summary[:1600].rstrip()}..."

    class BrandedPDF(pdf_class):
        def header(self):
            if self.page_no() == 1:
                return
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*GREY_MID)
            self.cell(
                0,
                10,
                safe_text("AI App Factory | Stock Research Assistant"),
                new_x="LMARGIN",
                new_y="NEXT",
            )
            self.set_draw_color(*LINE)
            self.line(20, self.get_y(), 190, self.get_y())
            self.ln(2)

        def footer(self):
            self.set_y(-22)
            self.set_draw_color(*LINE)
            self.line(20, self.get_y(), 190, self.get_y())
            self.ln(2)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*GREY_MID)
            self.cell(
                0,
                5,
                safe_text("Research aid - not investment advice. For internal use only."),
                align="L",
            )
            self.set_y(-14)
            self.cell(0, 5, f"{self.page_no()}", align="R")

        def section_heading(self, text: str) -> None:
            self.set_font("Helvetica", "B", 15)
            self.set_text_color(*NAVY)
            self.cell(0, 10, safe_text(text), new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*NAVY)
            self.set_line_width(0.4)
            self.line(20, self.get_y(), 65, self.get_y())
            self.ln(4)

        def body_text(self, text: Any, size: int = 10) -> None:
            self.set_font("Helvetica", "", size)
            self.set_text_color(*CHARCOAL)
            self.multi_cell(0, 5.5, safe_text(text))
            self.ln(2)

        def bullet_list(self, items: list[str]) -> None:
            self.set_font("Helvetica", "", 10)
            self.set_text_color(*CHARCOAL)
            for item in items:
                self.set_x(25)
                self.multi_cell(0, 5.5, safe_text(f"- {item}"))
            self.ln(2)

    pdf = BrandedPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Cover page
    pdf.add_page()
    pdf.set_fill_color(*WHITE)
    pdf.rect(0, 0, 210, 297, "F")

    # Header band
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, 210, 42, "F")
    pdf.set_y(14)
    pdf.set_x(20)
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(*WHITE)
    pdf.cell(0, 7, safe_text("AI App Factory"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(20)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(180, 190, 205)
    pdf.cell(0, 5, safe_text("Stock Research Assistant"))
    pdf.set_x(130)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(180, 190, 205)
    pdf.cell(0, 5, safe_text(report_date), align="R")

    # Title block
    pdf.set_y(75)
    pdf.set_x(20)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GREY_MID)
    pdf.cell(0, 6, safe_text("EQUITY RESEARCH"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 26)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(170, 13, safe_text(name))
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*SLATE)
    pdf.cell(0, 7, safe_text(f"NSE: {symbol}"), new_x="LMARGIN", new_y="NEXT")

    # Verdict panel
    pdf.ln(14)
    panel_y = pdf.get_y()
    pdf.set_fill_color(*GREY_LIGHT)
    pdf.set_draw_color(*LINE)
    pdf.rect(20, panel_y, 170, 38, "FD")
    pdf.set_xy(25, panel_y + 7)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*NAVY)
    pdf.cell(40, 24, safe_text(verdict), align="L")
    pdf.set_xy(70, panel_y + 8)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*CHARCOAL)
    pdf.cell(0, 7, safe_text("Composite score"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(70, panel_y + 17)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 10, safe_text(f"{composite:.1f} / 10"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(140, panel_y + 8)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*CHARCOAL)
    pdf.cell(0, 7, safe_text("Risk rating"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(140, panel_y + 17)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 10, safe_text("Moderate"), new_x="LMARGIN", new_y="NEXT")

    # Bottom metadata
    pdf.set_y(258)
    pdf.set_x(20)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*GREY_MID)
    doc_id = re.sub(r"[^A-Za-z0-9_-]+", "_", symbol).strip("_") or "STOCK"
    for line in [
        "Analyst: AI Research Team",
        "Time horizon: 12 months",
        f"Document ID: {doc_id}-ER-{date.today().strftime('%Y%m%d')}-001",
    ]:
        pdf.cell(0, 5, safe_text(line), new_x="LMARGIN", new_y="NEXT")

    # Executive Summary
    pdf.add_page()
    pdf.section_heading("Executive Summary")
    pdf.body_text(summary or "No executive summary available.")

    # Scorecard
    pdf.add_page()
    pdf.section_heading("Scorecard")
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(*WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(70, 10, safe_text("Dimension"), border=0, align="L")
    pdf.cell(40, 10, safe_text("Score"), border=0, align="C")
    pdf.cell(80, 10, safe_text("Assessment"), border=0, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*LINE)
    pdf.line(20, pdf.get_y(), 190, pdf.get_y())
    pdf.ln(2)

    def score_assessment(score: float) -> str:
        if score >= 7.5:
            return "Strong"
        if score >= 6.5:
            return "Positive"
        if score >= 5.5:
            return "Neutral"
        return "Weak"

    for dim, score in scores.items():
        pdf.set_fill_color(*GREY_LIGHT)
        pdf.rect(20, pdf.get_y(), 170, 10, "F")
        pdf.set_text_color(*CHARCOAL)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(70, 10, safe_text(dim))
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(40, 10, safe_text(f"{score:.1f}/10"), align="C")
        pdf.cell(80, 10, safe_text(score_assessment(score)))
        pdf.ln(12)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 8, safe_text("Composite Verdict"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*CHARCOAL)
    pdf.multi_cell(
        0,
        6,
        safe_text(
            f"{verdict} - Composite score {composite:.1f}/10. "
            "Based on fundamentals, technicals, sentiment, and risk assessment."
        ),
    )

    # Disclaimer
    pdf.add_page()
    pdf.section_heading("Disclaimer")
    pdf.body_text(
        "This report is for research workflow support and education only. "
        "It is not investment advice, a recommendation, or a solicitation to buy or sell securities. "
        "Verify all figures with official filings and consult a SEBI-registered investment adviser before acting."
    )

    output = pdf.output(dest="S")
    if isinstance(output, bytearray):
        return bytes(output)
    if isinstance(output, bytes):
        return output
    return output.encode("latin-1", "replace")


def build_report_text(data: dict[str, Any], result: dict[str, Any]) -> str:
    score_lines = [
        f"{name}: {get_agent_output(result, data, name).score:.1f}/10"
        for name in SCORE_ORDER
    ]
    return "\n".join(
        [
            f"{data.get('name', 'Stock Report')} ({data.get('symbol', '')})",
            f"Generated: {result.get('generated_at', data.get('as_of', ''))}",
            f"Verdict: {result.get('verdict', 'Unavailable')}",
            f"Composite score: {result.get('composite', 0):.1f}/10",
            "",
            "Scores:",
            *score_lines,
            "",
            "Executive Summary:",
            str(result.get("final_report", "")),
        ]
    )


def report_download_payload(data: dict[str, Any], result: dict[str, Any]) -> tuple[bytes, str, str]:
    filename_base = re.sub(r"[^A-Za-z0-9_-]+", "_", str(data.get("base_symbol") or data.get("symbol") or "stock_report")).strip("_")
    try:
        from fpdf import FPDF

        pdf = build_report_pdf(data, result, FPDF)
        return pdf, f"{filename_base}_analysis.pdf", "application/pdf"
    except Exception:
        text = build_report_text(data, result).encode("utf-8")
        return text, f"{filename_base}_analysis.txt", "text/plain"


def render_stock_header(data: dict[str, Any]) -> None:
    stock_header_card(data)


def render_scorecards(outputs: dict[str, AgentResult]) -> None:
    cols = st.columns(4)
    for col, label in zip(cols, SCORE_ORDER):
        result = outputs.get(label) or AgentResult(label, "No agent notes were returned.", 5.0, "local")
        with col:
            score_card(label, result.score, 10)
            st.caption(f"{result.source.title()} analysis")


def render_verdict(result: dict[str, Any]) -> None:
    verdict, _ = verdict_for_score(result["composite"])
    ui.card(
        title="Composite Verdict",
        content=f"{result['composite']:.1f}/10",
        description=f"{verdict} · Generated {result['generated_at']}",
        key="composite_verdict_card",
    )
    verdict_badge(verdict)
    status_pill("Mode", str(result.get("mode", "agent")))


def render_chart(data: dict[str, Any]) -> None:
    hist = data["history"]
    required = {"Open", "High", "Low", "Close"}
    fig = go.Figure()
    if data.get("source") == "screener_fallback":
        st.info(
            "Price chart is unavailable because Yahoo Finance data was temporarily blocked. "
            "The report below uses Screener.in fundamentals + web-search context instead."
        )
        return
    if required.issubset(hist.columns):
        fig.add_trace(
            go.Candlestick(
                x=hist.index,
                open=hist["Open"],
                high=hist["High"],
                low=hist["Low"],
                close=hist["Close"],
                name="OHLC",
                increasing_line_color="#22c55e",
                decreasing_line_color="#ef4444",
            )
        )
    else:
        fig.add_trace(
            go.Scatter(
                x=hist.index,
                y=hist["Close"],
                mode="lines",
                name="Close",
                line=dict(color="#38bdf8", width=2),
                hovertemplate="%{x|%d %b %Y}<br>Close: ₹%{y:,.2f}<extra></extra>",
            )
        )

    for column, color in (("EMA20", "#22c55e"), ("EMA50", "#f59e0b")):
        if column in hist.columns:
            fig.add_trace(
                go.Scatter(
                    x=hist.index,
                    y=hist[column],
                    mode="lines",
                    name=column,
                    line=dict(color=color, width=1.5),
                    hovertemplate=f"%{{x|%d %b %Y}}<br>{column}: ₹%{{y:,.2f}}<extra></extra>",
                )
            )

    fig.update_layout(
        template="plotly_dark",
        height=460,
        margin=dict(l=8, r=8, t=18, b=8),
        paper_bgcolor="#09111f",
        plot_bgcolor="#101b2c",
        font=dict(color="#f5f7fb"),
        hovermode="x unified",
        xaxis=dict(gridcolor="rgba(159,176,199,0.12)", rangeslider=dict(visible=False)),
        yaxis=dict(gridcolor="rgba(159,176,199,0.12)", tickprefix="₹"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_result(data: dict[str, Any], result: dict[str, Any]) -> None:
    render_stock_header(data)
    executive_verdict_strip(data, result)

    section_title("Research Scorecard")
    score_cols = st.columns([1, 1, 1, 1, 0.92])
    for col, label in zip(score_cols[:4], SCORE_ORDER):
        agent_result = get_agent_output(result, data, label)
        with col:
            score_card(label, agent_result.score, 10)
            st.caption(f"{agent_result.source.title()} analysis")
    with score_cols[4]:
        render_verdict(result)

    f = data["fundamentals"]
    t = data["technicals"]
    kpis = [
        ("Market Cap", money(f.get("market_cap")), data["exchange"], "🏦"),
        ("P/E", number(f.get("trailing_pe")), "Trailing", "📈"),
        ("RSI", number(t.get("rsi")), t.get("trend"), "⚡"),
        ("1Y Return", number(t.get("return_1y_pct"), "%"), "Price momentum", "↗"),
    ]

    overview_tab, chart_tab, agent_tab, metrics_tab, deep_tab = st.tabs(
        ["Overview", "Price chart", "Agent breakdown", "Key metrics", "Deep Research"]
    )

    with overview_tab:
        left, right = st.columns([1.45, 0.75])
        with left:
            section_title("Executive Summary")
            with st.container(border=True):
                st.markdown(result["final_report"])
            st.caption(_market_data_source_badge(data))
            report_bytes, report_filename, report_mime = report_download_payload(data, result)
            st.download_button(
                "📥 Download Report",
                data=report_bytes,
                file_name=report_filename,
                mime=report_mime,
                key=f"download_report_{data.get('base_symbol', 'stock')}",
            )
        with right:
            section_title("What to check next")
            with st.container(border=True):
                st.markdown(
                    """
                    - Validate the thesis against latest company filings and concall commentary.
                    - Compare valuation with sector peers before acting.
                    - Treat weak or fallback sentiment as a research gap, not a conclusion.
                    """
                )

    with chart_tab:
        section_title("Price Chart")
        render_chart(data)

    with agent_tab:
        section_title("Agent Details")
        for label in SCORE_ORDER:
            agent_result = get_agent_output(result, data, label)
            with st.expander(
                f"{label} - {agent_result.score:.1f}/10",
                expanded=label == "Fundamentals",
            ):
                st.caption(f"{agent_result.source.title()} analysis")
                st.markdown(agent_result.content)
        with st.expander("How this section is scored"):
            st.write(
                "Each agent starts with the same market context. Agent mode uses DeepSeek + web search; "
                "local mode uses deterministic fallback scoring from the available market data."
            )

    with metrics_tab:
        section_title("Core Metrics")
        cols = st.columns(4)
        for col, args in zip(cols, kpis):
            with col:
                kpi_card(*args)

        fundamentals_col, technicals_col = st.columns(2)
        with fundamentals_col:
            section_title("Fundamentals")
            with st.container(border=True):
                st.write(f"**Forward P/E:** {number(f.get('forward_pe'))}")
                st.write(f"**Price / Book:** {number(f.get('price_to_book'))}")
                st.write(f"**ROE:** {pct(f.get('roe'))}")
                st.write(f"**Revenue Growth:** {pct(f.get('revenue_growth'))}")
                st.write(f"**Profit Margin:** {pct(f.get('profit_margins'))}")
                st.write(f"**Debt / Equity:** {number(f.get('debt_to_equity'))}")
        with technicals_col:
            section_title("Technicals")
            with st.container(border=True):
                st.write(f"**Trend:** {t.get('trend')}")
                st.write(f"**EMA20:** {number(t.get('ema20'))}")
                st.write(f"**EMA50:** {number(t.get('ema50'))}")
                st.write(f"**Support:** ₹{t.get('support'):.2f}")
                st.write(f"**Resistance:** ₹{t.get('resistance'):.2f}")
                st.write(f"**60D Volatility:** {number(t.get('volatility_60d_pct'), '%')}")

    email = st.session_state.get("user_email", "")
    user = get_user(email) if email else None
    plan = user.get("plan", "free") if isinstance(user, dict) else getattr(user, "plan", "free")

    with deep_tab:
        if not REQUIRE_AUTH:
            st.info("🔓 Available during beta")
            render_deep_research_tab(data, result, data.get("symbol"))
        elif plan == "free":
            st.warning("🔒 Deep Research is a Pro feature")
            st.markdown(
                "Get peer comparison, analyst targets, valuation "
                "models, governance checks, and an enhanced PDF report."
            )
            st.info("Upgrade to Pro (₹199/mo) to unlock Deep Research.")
            from payment import _render_upgrade_ui
            _render_upgrade_ui(email, plan)
        else:
            render_deep_research_tab(data, result, data.get("symbol"))


# ---------------------------------------------------------------------------
# Deep Research tab helpers
# ---------------------------------------------------------------------------

DEEP_RESEARCH_SECTIONS = [
    ("peer_comparison", "Peer Comparison"),
    ("analyst_targets", "Analyst Consensus"),
    ("financial_trends", "Financial Trends"),
    ("risk_flags", "Risk Flags"),
    ("valuation", "Valuation"),
    ("governance", "Governance"),
    ("thesis", "Investment Thesis"),
    ("enhanced_pdf", "Enhanced PDF"),
]


def _deep_get_api_key() -> str:
    for key in ("api_key", "deepseek_api_key", "DEEPSEEK_API_KEY"):
        value = st.session_state.get(key)
        if value:
            return str(value)
    try:
        return str(st.secrets.get("DEEPSEEK_API_KEY", ""))
    except Exception:
        return ""


def _deep_symbol(data: dict, fallback_symbol: str | None = None) -> str:
    """Resolve the active symbol for Deep Research tab with multi-source fallback.

    Priority: explicit param → data dict → session_state symbol → session_state market_data →
    sidebar text input → empty string.
    """
    raw = (
        fallback_symbol
        or data.get("symbol")
        or data.get("nse_symbol")
        or data.get("ticker")
        or st.session_state.get("sra_market_data", {}).get("symbol")
        or st.session_state.get("symbol_input")
        or ""
    )
    symbol = str(raw).strip().upper()
    if symbol and not symbol.endswith(".NS") and not symbol.endswith(".BO"):
        symbol = f"{symbol}.NS"
    return symbol


def _deep_data_frame(rows: list[dict]) -> None:
    if not rows:
        st.info("No table rows available yet.")
        return
    frame = pd.DataFrame(rows)
    st.dataframe(frame, use_container_width=True, hide_index=True)


def _deep_metric_row(items: list[tuple[str, object]]) -> None:
    cols = st.columns(min(max(len(items), 1), 4))
    for index, (label, value) in enumerate(items):
        with cols[index % len(cols)]:
            st.metric(label, "—" if value is None else value)


def _render_peer_comparison(section: dict) -> None:
    payload = section.get("data", {}) if isinstance(section, dict) else {}
    if section.get("warnings"):
        st.warning("\n".join(section.get("warnings", [])))
    _deep_data_frame(payload.get("table", []))
    flags = payload.get("valuation_flags", [])
    if flags:
        st.markdown("#### Premium / Discount Flags")
        _deep_data_frame(flags)


def _render_analyst_targets(section: dict) -> None:
    payload = section.get("data", {}) if isinstance(section, dict) else {}
    if section.get("warnings"):
        st.warning("\n".join(section.get("warnings", [])))
    _deep_metric_row([
        ("Current Price", payload.get("current_price")),
        ("Mean Target", payload.get("target_mean_price")),
        ("Upside / Downside %", payload.get("upside_downside_pct")),
        ("Analyst Count", payload.get("number_of_analyst_opinions")),
    ])
    st.json({
        "target_high_price": payload.get("target_high_price"),
        "target_low_price": payload.get("target_low_price"),
        "recommendation_key": payload.get("recommendation_key"),
        "recommendation_mean": payload.get("recommendation_mean"),
        "has_coverage": payload.get("has_coverage"),
    })


def _render_financial_trends(section: dict) -> None:
    payload = section.get("data", {}) if isinstance(section, dict) else {}
    if section.get("warnings"):
        st.warning("\n".join(section.get("warnings", [])))
    figures = payload.get("figures", {})
    if not figures:
        st.info("Trend charts are unavailable until Screener financial data is parsed.")
    for title, figure_json in figures.items():
        st.plotly_chart(go.Figure(figure_json), use_container_width=True)
    summary = payload.get("summary", [])
    if summary:
        st.markdown("#### Summary")
        _deep_data_frame(summary)


def _render_risk_flags(section: dict) -> None:
    payload = section.get("data", {}) if isinstance(section, dict) else {}
    if section.get("warnings"):
        st.warning("\n".join(section.get("warnings", [])))
    _deep_metric_row([
        ("Triggered Flags", payload.get("total_flags")),
        ("Checks Completed", payload.get("total_checked")),
    ])
    _deep_data_frame(payload.get("flags", []))


def _render_valuation(section: dict) -> None:
    payload = section.get("data", {}) if isinstance(section, dict) else {}
    if section.get("warnings"):
        st.warning("\n".join(section.get("warnings", [])))
    fair = payload.get("fair_value_range", {}) or {}
    _deep_metric_row([
        ("Current Price", payload.get("current_price")),
        ("Fair Value Base", fair.get("base")),
        ("Upside %", payload.get("upside_pct")),
    ])
    st.markdown("#### Fair Value Range")
    st.json(fair)
    st.markdown("#### Methods")
    _deep_data_frame(payload.get("methods", []))
    if payload.get("sensitivity_table"):
        st.markdown("#### DCF Sensitivity")
        rows = payload["sensitivity_table"]
        if len(rows) > 1:
            st.dataframe(pd.DataFrame(rows[1:], columns=rows[0]), use_container_width=True, hide_index=True)


def _render_governance(section: dict) -> None:
    payload = section.get("data", {}) if isinstance(section, dict) else {}
    if section.get("warnings"):
        st.warning("\n".join(section.get("warnings", [])))
    _deep_metric_row([
        ("Governance Score", payload.get("governance_score")),
        ("Promoter Holding", payload.get("promoter_holding")),
        ("Pledged %", payload.get("pledged_pct")),
        ("Promoter Trend", payload.get("promoter_trend")),
    ])
    if payload.get("flags"):
        st.markdown("#### Governance Flags")
        for item in payload.get("flags", []):
            st.warning(item)


def _render_thesis(section: dict) -> None:
    payload = section.get("data", {}) if isinstance(section, dict) else {}
    if section.get("warnings"):
        st.warning("\n".join(section.get("warnings", [])))
    st.markdown(f"**One-line thesis:** {payload.get('one_line_thesis', 'Unavailable')}")
    st.markdown("#### Company Overview")
    st.write(payload.get("company_overview") or "Unavailable")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### Bull Case")
        for item in payload.get("bull_case", []):
            st.success(item)
    with col2:
        st.markdown("#### Bear Case")
        for item in payload.get("bear_case", []):
            st.error(item)
    st.markdown("#### Key Catalysts")
    for item in payload.get("key_catalysts", []):
        st.info(item)
    st.markdown("#### What the Market May Be Missing")
    st.write(payload.get("market_missing") or "Unavailable")


def _render_enhanced_pdf(data: dict, quick_result: dict, deep_result: dict, symbol: str) -> None:
    pdf_bytes = build_enhanced_pdf(data, quick_result, deep_result)
    st.download_button(
        label="Download Enhanced Deep Research PDF",
        data=pdf_bytes,
        file_name=f"{symbol.replace('.', '_')}_deep_research_report.pdf",
        mime="application/pdf",
        use_container_width=True,
    )


def _render_deep_placeholder() -> None:
    st.info("Run Deep Research to populate these sections. The placeholders below keep the 5th tab shell visible before execution.")
    for _, label in DEEP_RESEARCH_SECTIONS:
        with st.expander(label, expanded=False):
            st.write("Pending. Click **Run Deep Research** above to generate this section.")


def render_deep_research_tab(data: dict, quick_result: dict, symbol: str | None = None) -> None:
    if "deep_research" not in st.session_state:
        st.session_state["sra_deep_research"] = {}

    # Persist symbol from sidebar input if explicit symbol wasn't passed
    if not symbol:
        symbol = st.session_state.get("symbol_input", "")

    active_symbol = _deep_symbol(data, symbol)
    if not active_symbol:
        st.error("Unable to determine symbol for Deep Research.")
        return

    st.markdown("### Deep Research")
    st.caption("Extended fundamentals, peers, analyst consensus, risk flags, valuation, governance, thesis, and enhanced PDF.")

    peer_text = st.text_input(
        "Optional peer tickers",
        value="",
        placeholder="Example: HDFCBANK.NS, ICICIBANK.NS",
        key=f"deep_peer_input_{active_symbol}",
        help="Comma-separated NSE tickers. .NS is added automatically when missing.",
    )

    col_run, col_status = st.columns([1, 2])
    with col_run:
        run_clicked = st.button("Run Deep Research", type="primary", use_container_width=True, key=f"run_deep_{active_symbol}")
    with col_status:
        existing = st.session_state["sra_deep_research"].get(active_symbol)
        st.caption("Cached for this session." if existing else "No deep research result yet for this symbol.")

    if run_clicked:
        api_key = _deep_get_api_key()
        peer_tickers = [item.strip() for item in peer_text.split(",") if item.strip()]
        wit = st.empty()
        wit.markdown(
            '<p class="analysis-wit">🧠 Deep Research engaged — pulling financials, analyst reports, risk flags, and peer data. This is thorough work.</p>',
            unsafe_allow_html=True,
        )
        result = run_deep_research(active_symbol, data, api_key, peer_tickers=peer_tickers)
        st.session_state["sra_deep_research"][active_symbol] = result
        wit.empty()
        if result.get("warnings"):
            st.warning("\n".join(result.get("warnings", [])[:8]))
        st.success("Deep Research completed.")

    deep_result = st.session_state["sra_deep_research"].get(active_symbol)
    if not deep_result:
        _render_deep_placeholder()
        return

    with st.expander("Peer Comparison", expanded=True):
        _render_peer_comparison(deep_result.get("peer_comparison", {}))
    with st.expander("Analyst Consensus", expanded=False):
        _render_analyst_targets(deep_result.get("analyst_targets", {}))
    with st.expander("Financial Trends", expanded=False):
        _render_financial_trends(deep_result.get("financial_trends", {}))
    with st.expander("Risk Flags", expanded=False):
        _render_risk_flags(deep_result.get("risk_flags", {}))
    with st.expander("Valuation", expanded=False):
        _render_valuation(deep_result.get("valuation", {}))
    with st.expander("Governance", expanded=False):
        _render_governance(deep_result.get("governance", {}))
    with st.expander("Investment Thesis", expanded=False):
        _render_thesis(deep_result.get("thesis", {}))
    with st.expander("Enhanced PDF", expanded=False):
        _render_enhanced_pdf(data, quick_result, deep_result, active_symbol)


def user_field(user: Any, key: str, default: Any) -> Any:
    if isinstance(user, dict):
        return user.get(key, default)
    return getattr(user, key, default)


def render_footer(email: str) -> None:
    if not email:
        return
    user = get_user(email)
    if isinstance(user, dict):
        plan = user.get("plan", "free")
        used = user.get("analyses_used", 0)
        limit = user.get("analyses_limit", 5)
    else:
        plan = user_field(user, "plan", "free")
        used = st.session_state.get("_session_report_count", 0)
        limit = user_field(user, "analyses_limit", 5)
    footer_html = (
        f'<div class="footer"><strong>{APP_TITLE}</strong> · Free during beta</div>'
        if not REQUIRE_AUTH
        else f'<div class="footer"><strong>{APP_TITLE}</strong> · User: {escape(str(email))} · Plan: {escape(str(plan).upper())} · Reports: {used}/{limit}</div>'
    )
    st.markdown(
        footer_html,
        unsafe_allow_html=True,
    )


def report_file_symbol(symbol: str) -> str:
    return report_history_service.report_file_symbol(symbol)


def report_path_for(symbol: str, timestamp: str) -> Path:
    return report_history_service.report_path_for(REPORTS_DIR, symbol, timestamp)


def timestamp_from_report_path(path: Path) -> str:
    return report_history_service.timestamp_from_report_path(path)


def json_safe(value: Any) -> Any:
    return report_history_service.json_safe(value)


def restore_dataframe(value: Any) -> pd.DataFrame:
    return report_history_service.restore_dataframe(value)


def restore_report_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return report_history_service.restore_report_payload(payload)


def read_report_file(path: Path) -> dict[str, Any] | None:
    return report_history_service.read_report_file(path)


def enforce_report_cap() -> None:
    report_history_service.enforce_report_cap(REPORTS_DIR, MAX_REPORT_FILES)


def save_report(data: dict[str, Any], result: dict[str, Any], email: str = "") -> dict[str, str] | None:
    return report_history_service.save_report(
        data,
        result,
        email=email,
        reports_dir=REPORTS_DIR,
        max_report_files=MAX_REPORT_FILES,
    )


def load_history_from_disk() -> None:
    email = str(st.session_state.get("user_email", "") or "").strip().lower()
    if not email:
        st.session_state.sra_report_history = []
        st.session_state["_history_email"] = ""
        return
    history = report_history_service.load_history_items(REPORTS_DIR, email, MAX_REPORT_FILES)
    if history is None:
        return
    st.session_state.sra_report_history = history
    st.session_state["_history_email"] = email


def load_report(symbol: str, timestamp: str) -> bool:
    payload = report_history_service.load_report_payload(REPORTS_DIR, symbol, timestamp)
    if payload is None:
        return False
    data, result = payload
    st.session_state.sra_market_data = data
    st.session_state.sra_result = result
    return True


def report_payload_from_history(item: dict[str, Any]) -> tuple[bytes, str, str] | None:
    return report_history_service.report_payload_from_history(
        item,
        reports_dir=REPORTS_DIR,
        download_builder=report_download_payload,
    )


def add_history(data: dict[str, Any], result: dict[str, Any]) -> None:
    email = str(st.session_state.get("user_email", "") or "").strip().lower()
    item = {
        "symbol": data["base_symbol"],
        "name": data["name"],
        "verdict": result["verdict"],
        "score": result["composite"],
        "time": result["generated_at"],
        "email": email,
    }
    saved = save_report(data, result, email=email)
    if saved:
        item.update(saved)
    history = [item] + list(st.session_state.sra_report_history)
    st.session_state.sra_report_history = history[:MAX_REPORT_FILES]


def render_empty_preview() -> None:
    st.markdown(
        """
        <section class="empty-preview" aria-label="Sample dashboard preview">
            <div class="empty-preview-grid">
                <article class="empty-preview-card positive" style="--accent:#22c55e;">
                    <span>Market Analysis</span>
                    <strong>+2.4%</strong>
                    <small>&uarr; Sample momentum signal</small>
                </article>
                <article class="empty-preview-card neutral" style="--accent:#f59e0b;">
                    <span>Agent Insights</span>
                    <strong>4 views</strong>
                    <small>Fundamentals, technicals, sentiment, risk</small>
                </article>
                <article class="empty-preview-card negative" style="--accent:#ef4444;">
                    <span>Risk Assessment</span>
                    <strong>-1.1%</strong>
                    <small>&darr; Sample downside watch</small>
                </article>
            </div>
            <div class="empty-steps">
                <div class="empty-step"><b>1</b><span>Choose a company name or NSE ticker from the sidebar.</span></div>
                <div class="empty-step"><b>2</b><span>Run analysis during the free beta.</span></div>
                <div class="empty-step"><b>3</b><span>Review verdict, scorecards, and agent notes.</span></div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_hero_action(symbol: str) -> bool:
    """Above-the-fold action strip so the report CTA is visible before scrolling."""
    sym = escape((symbol or "SBIN").upper())
    clicked = st.button(
        f"Generate {sym} Research Report",
        key="hero_analyze_button",
        type="primary",
        use_container_width=True,
        disabled=(not symbol.strip()),
    )
    pricing_caption = "Free during beta" if not REQUIRE_AUTH else "Free: 5 reports · Pro: 100 reports · ₹199/mo"
    st.markdown(
        f'<p class="hero-pricing-caption" style="margin-left:0; padding-left:0.5rem;">{pricing_caption}</p>',
        unsafe_allow_html=True,
    )
    return clicked


def render_analysis_progress_shell(active_label: str = "Resolving ticker") -> None:
    steps = [
        "Resolving ticker",
        "Fetching market data",
        "Running AI analysis",
        "Assessing risk",
        "Generating verdict",
    ]
    active_index = 0
    label_lower = active_label.lower()
    for index, step in enumerate(steps):
        if step.lower() in label_lower or step.split()[0].lower() in label_lower:
            active_index = index
    step_html = "".join(
        f"""
        <div class="analysis-step {'is-active' if index == active_index else 'is-complete' if index < active_index else ''}">
            <b>{index + 1}</b>
            <span>{escape(step)}</span>
        </div>
        """
        for index, step in enumerate(steps)
    )
    st.markdown(
        f"""
        <section class="analysis-progress-shell" aria-label="Analysis progress">
            <div>
                <span>Generating report</span>
                <strong>{escape(active_label)}</strong>
            </div>
            <div class="analysis-stepper">{step_html}</div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    init_state()
    inject_theme(st.session_state.get("theme", "light"))

    # ── Auth gate in main content area (mobile-friendly) ──
    auth_email = render_auth_gate()

    # Sidebar: secondary controls (theme, brand, access badge, history, help).
    # The company picker has moved to the main content area.
    email, symbol = render_sidebar()

    # Prefer the email from render_auth_gate if render_sidebar returned empty
    if not email and auth_email:
        email = auth_email

    # ── Only show hero, CTA, and sample report when authenticated ──
    if not (is_authenticated() and auth_email):
        # Unauthenticated: show a clean teaser without CTA or sample report
        st.markdown(
            """
            <div style="max-width:640px; margin:2rem auto 0; text-align:center;">
                <h2 style="font-size:1.5rem; margin-bottom:0.5rem;">
                    AI-Powered NSE Stock Research
                </h2>
                <p style="opacity:0.7; font-size:0.95rem; line-height:1.5;">
                    Five-agent equity research with fundamentals, technicals,
                    sentiment analysis, risk scoring, and a coordinated verdict —
                    all in one clean report.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        render_footer(email)
        render_main_sign_out()
        return

    page_header(
        APP_TITLE,
        "Five-agent equity research for NSE stocks with fundamentals, technicals, sentiment, risk, and a coordinated verdict.",
    )

    # ── Company picker + quick-picks IN MAIN CONTENT (mobile-first) ──
    symbol = render_research_setup()

    hero_analyze = render_hero_action(symbol)

    api_key = get_deepseek_key()
    if not api_key:
        with st.sidebar:
            info_alert("DEEPSEEK_API_KEY missing. Using yfinance-only local scoring.", "warning")

    if hero_analyze:
        st.session_state.sra_market_data = None
        st.session_state.sra_result = None

        if not require_payment(email):
            st.stop()

        try:
            progress_shell = st.empty()
            label_placeholder = st.empty()
            resolved = resolve_ticker(symbol)
            nse_symbol = resolved["symbol"]
            if not nse_symbol:
                raise ValueError(ticker_not_found_message(symbol))
            progress_shell.empty()
            with progress_shell.container():
                render_analysis_progress_shell("Resolving ticker")
            label_placeholder.markdown(f"**Resolving ticker: {symbol} → {nse_symbol}**")
            wit_placeholder = st.empty()
            wit_placeholder.markdown(
                f'<p class="analysis-wit">🔍 Finding the right ticker. Good analysis starts with the correct symbol.</p>',
                unsafe_allow_html=True,
            )
            progress_bar = st.progress(0)
            progress_bar.progress(8)

            _wit_idx = [0]

            def update_progress(value: int, label: str | None = None) -> None:
                if label:
                    display_label = label.strip().rstrip(".")
                    if display_label == "Generating report":
                        display_label = "Generating verdict"
                    progress_shell.empty()
                    with progress_shell.container():
                        render_analysis_progress_shell(display_label)
                    label_placeholder.markdown(f"**{label}**")
                    wit_placeholder.markdown(
                        f'<p class="analysis-wit">💡 {ROTATING_WIT[_wit_idx[0] % len(ROTATING_WIT)]}</p>',
                        unsafe_allow_html=True,
                    )
                    _wit_idx[0] += 1
                progress_bar.progress(value)

            progress_shell.empty()
            with progress_shell.container():
                render_analysis_progress_shell("Fetching market data")
            label_placeholder.markdown("**Fetching market data**")
            wit_placeholder.markdown(
                f'<p class="analysis-wit">💡 {ROTATING_WIT[0]}</p>',
                unsafe_allow_html=True,
            )
            data, result = run_analysis(symbol, api_key, update_progress, resolved=resolved)
            progress_bar.progress(100)
            progress_bar.empty()
            label_placeholder.empty()
            wit_placeholder.empty()
            progress_shell.empty()
            st.session_state.sra_market_data = data
            st.session_state.sra_result = result
            add_history(data, result)
            track_usage(email, "stock_research")
        except Exception as exc:
            if "progress_bar" in locals():
                progress_bar.empty()
            if "label_placeholder" in locals():
                label_placeholder.empty()
            if "wit_placeholder" in locals():
                wit_placeholder.empty()
            if "progress_shell" in locals():
                progress_shell.empty()

            log_error("main/run_analysis", str(exc), data={"symbol": symbol}, exc=exc)

            if is_rate_limit_error(exc):
                st.error(
                    "All data sources (Yahoo Finance, Screener.in, and web price feeds) "
                    "are temporarily unreachable from this cloud server. "
                    "Shared IPs on Hugging Face Spaces get rate-limited occasionally. "
                    "Please wait a minute and try again — your analysis will work."
                )
            else:
                st.error(f"Analysis failed: {exc}")

    if st.session_state.sra_market_data and st.session_state.sra_result:
        render_result(st.session_state.sra_market_data, st.session_state.sra_result)
    else:
        sample_report_preview(symbol)

    render_footer(email)

    # ── Sign-out at the very bottom of the page (mobile-first) ──
    render_main_sign_out()


if __name__ == "__main__":
    main()
