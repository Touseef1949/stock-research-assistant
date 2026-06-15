"""Risk flag evaluation for Deep Research."""

from __future__ import annotations

from typing import Any


def _unwrap(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    return data.get("data") if isinstance(data.get("data"), dict) else data


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except Exception:
        return None


def _series(data: dict[str, Any], path: list[str]) -> list[float]:
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict):
            return []
        cursor = cursor.get(key)
    if not isinstance(cursor, list):
        return []
    out: list[float] = []
    for item in cursor:
        parsed = _safe_float(item)
        if parsed is not None:
            out.append(parsed)
    return out


def _get(data: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict):
            return default
        cursor = cursor.get(key)
    return cursor if cursor is not None else default


def _consecutive_declines(values: list[float], periods: int = 3) -> bool | None:
    if len(values) < periods + 1:
        return None
    recent = values[-(periods + 1):]
    return all(recent[index] > recent[index + 1] for index in range(periods))


def _growth_pct(start: float | None, end: float | None) -> float | None:
    if start in (None, 0) or end is None:
        return None
    try:
        return ((end - start) / abs(start)) * 100
    except Exception:
        return None


def _flag(name: str, triggered: bool | None, evidence: str, explanation: str, severity: str = "medium") -> dict[str, Any]:
    status = "unchecked" if triggered is None else "triggered" if triggered else "clear"
    return {
        "name": name,
        "triggered": triggered,
        "status": status,
        "severity": severity if triggered else "none" if triggered is False else "unknown",
        "evidence": evidence,
        "explanation": explanation,
    }


def evaluate_risk_flags(
    screener_data: dict[str, Any] | None,
    market_data: dict[str, Any] | None = None,
    peer_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate 12 accounting, operating, leverage, and governance red flags."""
    data = _unwrap(screener_data)
    peer = _unwrap(peer_data)
    market = market_data or {}
    warnings: list[str] = []

    flags: list[dict[str, Any]] = []

    quarterly_sales = _series(data, ["quarterly", "sales"])
    declining_revenue = _consecutive_declines(quarterly_sales, 3)
    flags.append(_flag(
        "Declining revenue for 3+ quarters",
        declining_revenue,
        f"Recent quarterly sales: {quarterly_sales[-4:] if quarterly_sales else 'unavailable'}",
        "Revenue declining across three consecutive quarters can indicate demand weakness or execution pressure.",
        "high",
    ))

    quarterly_opm = _series(data, ["quarterly", "opm_pct"])
    margin_compression = _consecutive_declines(quarterly_opm, 3)
    flags.append(_flag(
        "Margin compression for 3+ quarters",
        margin_compression,
        f"Recent quarterly OPM %: {quarterly_opm[-4:] if quarterly_opm else 'unavailable'}",
        "Sustained margin compression suggests pricing pressure, input-cost inflation, or operating deleverage.",
        "high",
    ))

    target_de = _safe_float(_get(data, ["ratios", "debt_to_equity"]))
    peer_de_median = _safe_float(_get(peer, ["peer_stats", "D/E", "median"]))
    if target_de is None or peer_de_median is None:
        rising_de = None
    else:
        rising_de = target_de > max(peer_de_median * 1.25, peer_de_median + 0.2)
    flags.append(_flag(
        "D/E above industry median",
        rising_de,
        f"Target D/E: {target_de}; peer median D/E: {peer_de_median}",
        "Leverage above peers reduces financial flexibility and can amplify earnings downside.",
        "medium",
    ))

    ocf = _series(data, ["cash_flow", "operating_cash_flow"])
    pat = _series(data, ["profit_loss", "net_profit"])
    negative_ocf_positive_pat = None
    if ocf and pat:
        negative_ocf_positive_pat = ocf[-1] < 0 < pat[-1]
    flags.append(_flag(
        "Negative OCF with positive PAT",
        negative_ocf_positive_pat,
        f"Latest OCF: {ocf[-1] if ocf else 'unavailable'}; latest PAT: {pat[-1] if pat else 'unavailable'}",
        "Profits not converting to operating cash flow can point to weak earnings quality.",
        "high",
    ))

    receivables = _series(data, ["balance_sheet", "receivables"])
    sales = _series(data, ["profit_loss", "sales"])
    receivables_faster = None
    if len(receivables) >= 2 and len(sales) >= 2:
        rec_growth = _growth_pct(receivables[-2], receivables[-1])
        sales_growth = _growth_pct(sales[-2], sales[-1])
        if rec_growth is not None and sales_growth is not None:
            receivables_faster = rec_growth > sales_growth + 10
    flags.append(_flag(
        "Receivables growing faster than sales",
        receivables_faster,
        f"Receivables: {receivables[-2:] if receivables else 'unavailable'}; Sales: {sales[-2:] if sales else 'unavailable'}",
        "Receivables outpacing sales may indicate aggressive revenue recognition or collection stress.",
        "medium",
    ))

    promoter = _series(data, ["shareholding", "promoter_pct"])
    promoter_decline = None
    if len(promoter) >= 2:
        promoter_decline = (promoter[0] - promoter[-1]) > 2
    flags.append(_flag(
        "Promoter holding declining by more than 2%",
        promoter_decline,
        f"Promoter holding trend: {promoter if promoter else 'unavailable'}",
        "Material promoter selling can be a governance or confidence signal that requires deeper investigation.",
        "medium",
    ))

    pledged = _series(data, ["shareholding", "pledged_promoter_pct"])
    high_pledge = pledged[-1] > 25 if pledged else None
    flags.append(_flag(
        "Promoter pledging above 25%",
        high_pledge,
        f"Latest pledged promoter holding %: {pledged[-1] if pledged else 'unavailable'}",
        "High promoter pledge can create forced-selling risk during market drawdowns.",
        "high",
    ))

    auditor_changes = _safe_float(_get(data, ["governance", "auditor_changes_3yr"]) or market.get("auditor_changes_3yr"))
    frequent_auditor_changes = auditor_changes > 1 if auditor_changes is not None else None
    flags.append(_flag(
        "Frequent auditor changes",
        frequent_auditor_changes,
        f"Auditor changes in last 3 years: {auditor_changes if auditor_changes is not None else 'unavailable'}",
        "Repeated auditor changes may indicate audit friction or governance complexity.",
        "high",
    ))

    rpt_ratio = _safe_float(_get(data, ["governance", "related_party_transactions_pct_sales"]) or market.get("related_party_transactions_pct_sales"))
    high_rpt = rpt_ratio > 10 if rpt_ratio is not None else None
    flags.append(_flag(
        "High related-party transactions",
        high_rpt,
        f"RPT as % of sales: {rpt_ratio if rpt_ratio is not None else 'unavailable'}",
        "High related-party transactions increase governance and transfer-pricing risk.",
        "medium",
    ))

    interest_coverage = _safe_float(_get(data, ["ratios", "interest_coverage"]))
    low_interest_coverage = interest_coverage < 1.5 if interest_coverage is not None else None
    flags.append(_flag(
        "Interest coverage below 1.5x",
        low_interest_coverage,
        f"Interest coverage: {interest_coverage if interest_coverage is not None else 'unavailable'}",
        "Low interest coverage suggests limited ability to service debt from operating earnings.",
        "high",
    ))

    contingent = _series(data, ["balance_sheet", "contingent_liabilities"])
    reserves = _series(data, ["balance_sheet", "reserves"])
    contingent_gt_networth = None
    if contingent and reserves and reserves[-1] != 0:
        contingent_gt_networth = contingent[-1] > reserves[-1]
    flags.append(_flag(
        "Contingent liabilities above net worth",
        contingent_gt_networth,
        f"Latest contingent liabilities: {contingent[-1] if contingent else 'unavailable'}; reserves/net worth proxy: {reserves[-1] if reserves else 'unavailable'}",
        "Large contingent liabilities can become real liabilities under adverse legal or regulatory outcomes.",
        "high",
    ))

    fcf = _series(data, ["cash_flow", "free_cash_flow"])
    dividend_paid = _series(data, ["cash_flow", "dividend_paid"])
    payout_gt_fcf = None
    if dividend_paid and fcf:
        payout_gt_fcf = abs(dividend_paid[-1]) > max(fcf[-1], 0)
    else:
        dividend_yield = _safe_float(_get(data, ["ratios", "dividend_yield"]))
        payout_ratio = _safe_float(market.get("payoutRatio") or _get(market, ["fundamentals", "payoutRatio"]))
        if payout_ratio is not None:
            payout_gt_fcf = payout_ratio > 1
        elif dividend_yield is not None and not fcf:
            payout_gt_fcf = None
    flags.append(_flag(
        "Dividend payout above FCF",
        payout_gt_fcf,
        f"Latest FCF: {fcf[-1] if fcf else 'unavailable'}; dividend paid: {dividend_paid[-1] if dividend_paid else 'unavailable'}",
        "Dividends above free cash flow can be unsustainable unless backed by temporary cash reserves.",
        "medium",
    ))

    total_checked = sum(1 for item in flags if item["status"] != "unchecked")
    total_flags = sum(1 for item in flags if item["triggered"] is True)
    if total_checked < len(flags):
        # Some checks are unavailable — this is normal for Screener data
        pass  # The UI already shows which checks are "unchecked"

    return {
        "success": True,
        "source": "computed",
        "data": {
            "total_flags": total_flags,
            "total_checked": total_checked,
            "flags": flags,
        },
        "warnings": warnings,
    }
