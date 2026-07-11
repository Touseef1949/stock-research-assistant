from __future__ import annotations

from html import escape
from typing import Any, Iterable

import streamlit as st
import streamlit_shadcn_ui as shadcn


def _safe(value: Any) -> str:
    return escape(str(value or ""), quote=True)


def _score_tone(score: float, max_score: float = 10.0) -> tuple[str, str, str]:
    ratio = score / max_score if max_score else 0
    if ratio >= 0.7:
        return "default", "#22c55e", "Healthy"
    if ratio >= 0.5:
        return "secondary", "#f59e0b", "Watch"
    return "destructive", "#ef4444", "Weak"


def page_header(title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <section class="page-header hero-card">
            <div class="product-masthead">
                <div class="product-mark" aria-hidden="true">SR</div>
                <div class="product-identity">
                    <strong>{_safe(title)}</strong>
                    <span>Decision intelligence for Indian equities</span>
                </div>
                <div class="system-status"><i></i> NSE market data</div>
            </div>
            <div class="hero-copy">
                <div class="eyebrow">Research workspace</div>
                <h1>From ticker to investment brief, in one workflow.</h1>
                <p>{_safe(subtitle)}</p>
                <div class="hero-proof" aria-label="Product capabilities">
                    <span>5 specialist agents</span>
                    <span>Source-traced evidence</span>
                    <span>Export-ready reports</span>
                </div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def sample_report_preview(symbol: str = "") -> None:
    # Use the currently selected ticker for the sample headline so it never
    # conflicts with the user's input. If no ticker is selected yet, fall back to INFY.
    sample_symbol = (symbol or "INFY").upper()
    sample_name = {
        "SBIN": "State Bank of India",
        "RELIANCE": "Reliance Industries",
        "TCS": "Tata Consultancy Services",
    }.get(sample_symbol, "Infosys")
    # Neutral sample reason/risk so the preview feels credible for any ticker.
    reason = "Resilient cash generation + margin stability"
    risk = "Macro/sector risk specific to the company"
    if sample_symbol in {"SBIN", "HDFCBANK", "ICICIBANK", "AXISBANK", "KOTAKBANK"}:
        reason = "Strong deposit franchise + improving asset quality"
        risk = "Credit cycle / interest-rate risk"
    elif sample_symbol in {"RELIANCE", "ONGC", "NTPC"}:
        reason = "Integrated operations + scale moat"
        risk = "Regulatory / commodity-price volatility"
    elif sample_symbol in {"INFY", "TCS", "WIPRO", "HCLTECH", "TECHM"}:
        reason = "Resilient cash generation + margin stability"
        risk = "US demand / discretionary IT spend slowdown"
    st.markdown(
        f"""
        <section class="sample-report-preview" aria-label="Sample report preview">
            <div class="sample-report-head">
                <div>
                    <span class="sample-kicker">Report preview</span>
                    <h3>{sample_symbol} / {_safe(sample_name)}</h3>
                    <p>An illustrative sample of the decision brief. Generate a report for current, source-traced analysis.</p>
                </div>
                <div class="sample-verdict-card">
                    <span>Sample verdict</span>
                    <strong>BUY</strong>
                    <small>Confidence 78%</small>
                </div>
            </div>
            <div class="sample-report-grid">
                <article>
                    <span>Key reason</span>
                    <strong>{_safe(reason)}</strong>
                </article>
                <article>
                    <span>Risk flag</span>
                    <strong>{_safe(risk)}</strong>
                </article>
            </div>
            <div class="sample-report-sections" aria-label="Included report sections">
                <span class="sample-report-section-pill">Executive brief</span>
                <span class="sample-report-section-pill">Price &amp; valuation</span>
                <span class="sample-report-section-pill">Risk flags</span>
                <span class="sample-report-section-pill">Evidence audit</span>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def executive_verdict_strip(data: dict[str, Any], result: dict[str, Any]) -> None:
    score = float(result.get("composite") or 0)
    confidence = max(0, min(100, round(score * 10)))
    st.markdown(
        f"""
        <section class="executive-verdict-strip" aria-label="Executive verdict">
            <div class="executive-verdict-copy">
                <span>Executive Verdict</span>
                <h3>{_safe(result.get("verdict", "Unavailable"))} on {_safe(data.get("base_symbol") or data.get("symbol"))}</h3>
                <p>Research aid &mdash; not financial advice</p>
            </div>
            <div class="executive-verdict-metrics">
                <div class="executive-verdict-metric"><span>Composite</span><strong>{score:.1f}/10</strong></div>
                <div class="executive-verdict-metric"><span>Confidence</span><strong>{confidence}%</strong></div>
                <div class="executive-verdict-metric"><span>Mode</span><strong>{_safe(result.get("mode", "agent")).upper()}</strong></div>
                <div class="executive-verdict-metric"><span>Generated</span><strong>{_safe(result.get("generated_at", data.get("as_of", "")))}</strong></div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, delta: str | None = None, icon: str | None = None) -> None:
    title = f"{icon} {label}" if icon else label
    shadcn.metric_card(
        title=title,
        content=str(value),
        description=str(delta or ""),
        key=f"kpi_{label.lower().replace(' ', '_')}",
    )


def score_card(label: str, score: float, max_score: float = 10.0) -> None:
    variant, color, state = _score_tone(score, max_score)
    shadcn.card(
        title=label,
        content=f"{score:.1f}/{max_score:g}",
        description=f"{state} agent score",
        key=f"score_card_{label.lower()}",
    )
    shadcn.badges(
        [(f"{score:.1f}/{max_score:g}", variant)],
        class_name=f"score-pill score-pill-{variant}",
        key=f"score_badge_{label.lower()}",
    )
    st.markdown(
        f"<div class='score-bar' aria-label='{_safe(label)} score'><span style='width:{min(score / max_score * 100, 100):.0f}%; background:{color};'></span></div>",
        unsafe_allow_html=True,
    )


def verdict_badge(verdict: str) -> None:
    variant = {
        "STRONG BUY": "default",
        "BUY": "default",
        "HOLD": "secondary",
        "SELL": "destructive",
        "AVOID": "destructive",
    }.get(str(verdict).upper(), "outline")
    shadcn.badges(
        [(str(verdict).upper(), variant)],
        class_name=f"verdict-badge verdict-{str(verdict).lower().replace(' ', '-')}",
        key=f"verdict_{str(verdict).lower().replace(' ', '_')}",
    )


def stock_header_card(data: dict[str, Any]) -> None:
    change = float(data.get("change") or 0)
    change_pct = float(data.get("change_pct") or 0)
    delta_class = "positive" if change >= 0 else "negative"
    delta_prefix = "+" if change >= 0 else ""
    st.markdown(
        f"""
        <article class="stock-header-card">
            <div class="stock-meta-row">
                <span>{_safe(data.get('exchange'))}</span>
                <span>{_safe(data.get('symbol'))}</span>
                <span>Updated {_safe(data.get('as_of'))}</span>
            </div>
            <div class="stock-title-row">
                <div>
                    <div class="stock-symbol">{_safe(data.get('base_symbol'))}</div>
                    <h2>{_safe(data.get('name'))}</h2>
                </div>
                <div class="stock-price-block">
                    <div class="stock-price">₹{float(data.get('price') or 0):,.2f}</div>
                    <div class="{delta_class}">{delta_prefix}{change:.2f} ({delta_prefix}{change_pct:.2f}%)</div>
                </div>
            </div>
        </article>
        """,
        unsafe_allow_html=True,
    )


def info_alert(message: str, type: str = "info") -> None:
    tone = {
        "info": "border-blue-500/40 bg-blue-500/10 text-blue-100",
        "warning": "border-amber-500/40 bg-amber-500/10 text-amber-100",
        "error": "border-red-500/40 bg-red-500/10 text-red-100",
        "success": "border-emerald-500/40 bg-emerald-500/10 text-emerald-100",
    }.get(type, "border-slate-500/40 bg-slate-500/10 text-slate-100")
    shadcn.alert(
        title=type.title(),
        description=message,
        class_name=tone,
        key=f"alert_{type}_{abs(hash(message))}",
    )


def section_title(text: str) -> None:
    st.markdown(
        f"""
        <div class='section-title-wrap'>
            <h3 class='section-title'>{_safe(text)}</h3>
        </div>
        """,
        unsafe_allow_html=True,
    )


def empty_state(title: str, description: str, steps: Iterable[str] | None = None) -> None:
    items = "".join(f"<li>{_safe(step)}</li>" for step in (steps or []))
    list_html = f"<ol>{items}</ol>" if items else ""
    st.markdown(
        f"""
        <section class="empty-state">
            <div class="empty-state-icon">📊</div>
            <h3>{_safe(title)}</h3>
            <p>{_safe(description)}</p>
            {list_html}
        </section>
        """,
        unsafe_allow_html=True,
    )


def status_pill(label: str, value: str) -> None:
    st.markdown(
        f"""
        <div class="status-pill">
            <span>{_safe(label)}</span>
            <strong>{_safe(value)}</strong>
        </div>
        """,
        unsafe_allow_html=True,
    )
