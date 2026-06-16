"""Screener.in client for the Deep Research module.

The functions in this file are intentionally defensive: Screener is an HTML
source and its markup can change. The parser extracts the most useful known
sections when available and returns structured warnings instead of raising.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any

try:
    import requests
except Exception:  # pragma: no cover - handled at runtime in user app
    requests = None  # type: ignore[assignment]


SCREENER_BASE = "https://www.screener.in/company"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _clean_symbol(symbol: str) -> str:
    """Normalize NSE symbol for Screener URLs."""
    cleaned = (symbol or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return re.sub(r"[^A-Z0-9&\-]", "", cleaned)


def _strip_tags(value: str) -> str:
    value = re.sub(r"<script.*?</script>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<style.*?</style>", " ", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", " ", value)
    value = unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def _to_number(value: Any) -> float | None:
    """Convert Screener/yfinance-style text into float, preserving signs."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text in {"-", "--", "NA", "N/A"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    # Normalize lakh/crore markers and currency symbols before extracting the number.
    text = text.replace(",", "").replace("%", "").replace("₹", "").replace("Rs.", "")
    text = text.replace("Cr.", "").replace("Cr", "").replace("x", "")
    # Convert "Lakhs" / "L" into crore-scale for consistency (1 Cr = 100 L).
    if re.search(r"\d+L$", text, re.I) or re.search(r"\d+\s+L$", text, re.I):
        text = text.replace("L", "").replace("l", "").replace("Lakhs", "").replace("Lakh", "")
        match = re.search(r"[-+]?\d*\.?\d+", text)
        if match:
            return float(match.group(0)) / 100
    match = re.search(r"[-+]?\d*\.?\d+", text)
    if not match:
        return None
    try:
        num = float(match.group(0))
        return -abs(num) if negative else num
    except ValueError:
        return None


def _extract_section(html: str, section_id: str) -> str:
    """Return the HTML of a Screener section by id, if present."""
    patterns = [
        rf'<section[^>]+id=["\']{re.escape(section_id)}["\'][^>]*>(.*?)</section>',
        rf'<div[^>]+id=["\']{re.escape(section_id)}["\'][^>]*>(.*?)</div>',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            return match.group(1)
    return ""


def _parse_table(section_html: str) -> dict[str, list[float | None]]:
    """Parse a Screener table into row-name -> numeric list."""
    rows: dict[str, list[float | None]] = {}
    if not section_html:
        return rows

    for row_html in re.findall(r"<tr[^>]*>(.*?)</tr>", section_html, flags=re.I | re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row_html, flags=re.I | re.S)
        cleaned_cells = [_strip_tags(cell) for cell in cells]
        cleaned_cells = [cell for cell in cleaned_cells if cell]
        if len(cleaned_cells) < 2:
            continue

        row_name = cleaned_cells[0].lower()
        row_name = re.sub(r"[^a-z0-9% /&()\-]", "", row_name).strip()
        values = [_to_number(cell) for cell in cleaned_cells[1:]]
        if row_name and any(value is not None for value in values):
            rows[row_name] = values
    return rows


def _find_row(rows: dict[str, list[float | None]], aliases: list[str], last_n: int = 5) -> list[float | None]:
    for alias in aliases:
        alias_lower = alias.lower()
        for row_name, values in rows.items():
            if alias_lower == row_name or alias_lower in row_name:
                return values[-last_n:]
    return []


def _extract_years(section_html: str, last_n: int = 5) -> list[str]:
    headers = re.findall(r"<th[^>]*>(.*?)</th>", section_html or "", flags=re.I | re.S)
    labels = [_strip_tags(header) for header in headers]
    labels = [label for label in labels if re.search(r"\d{4}|TTM|Mar|Dec|Sep|Jun", label, flags=re.I)]
    return labels[-last_n:]


def _extract_top_ratios(html: str) -> dict[str, float | None]:
    """Extract the summary ratio cards near the top of Screener pages."""
    ratios: dict[str, float | None] = {}
    # Screener usually renders ratio labels and numbers within list items.
    for item in re.findall(r"<li[^>]*>(.*?)</li>", html, flags=re.I | re.S):
        text = _strip_tags(item)
        if not text:
            continue
        known_labels = [
            "Market Cap", "Current Price", "High / Low", "Stock P/E", "Book Value",
            "Dividend Yield", "ROCE", "ROE", "Face Value", "Debt to equity",
            "Interest Coverage", "Current Ratio", "PEG Ratio",
        ]
        for label in known_labels:
            lowered = text.lower()
            label_lower = label.lower()
            if lowered.startswith(label_lower):
                value_text = text[len(label):]
                # Also accept labels with embedded currency symbols like '₹ 9,42,308 Cr.'
                value_text = re.sub(r"^[\s:₹Rs.]+", "", value_text)
                ratios[label.lower().replace(" ", "_").replace("/", "_")] = _to_number(value_text)
                break
    return ratios


def _growth_from_series(values: list[float | None], years: int) -> float | None:
    clean = [value for value in values if value is not None]
    if len(clean) < years + 1:
        return None
    start = clean[-(years + 1)]
    end = clean[-1]
    if start in (None, 0) or end is None or start <= 0:
        return None
    try:
        return ((end / start) ** (1 / years) - 1) * 100
    except Exception:
        return None


def _fetch_html(url: str, timeout: int) -> tuple[bool, str, str | None]:
    if requests is None:
        return False, "", "requests is not available in this environment"
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        if response.status_code >= 400:
            return False, "", f"Screener returned HTTP {response.status_code} for {url}"
        return True, response.text, None
    except Exception as exc:
        return False, "", f"Screener request failed for {url}: {exc}"


def fetch_screener_financials(symbol: str) -> dict[str, Any]:
    """Fetch and parse 5-year financial data from Screener.in.

    Parameters
    ----------
    symbol:
        NSE ticker, with or without the `.NS` suffix.

    Returns
    -------
    dict
        Structured result with `success`, `source`, `data`, and `warnings`.
    """
    warnings: list[str] = []
    cleaned_symbol = _clean_symbol(symbol)
    if not cleaned_symbol:
        return {"success": False, "source": "screener", "data": None, "warnings": ["Empty symbol supplied"]}

    urls = [
        f"{SCREENER_BASE}/{cleaned_symbol}/consolidated/",
        f"{SCREENER_BASE}/{cleaned_symbol}/",
    ]

    html = ""
    final_url = urls[0]
    for url in urls:
        ok, body, error = _fetch_html(url, timeout=15)
        if ok and body:
            html = body
            final_url = url
            break
        if error:
            warnings.append(error)

    if not html:
        return {
            "success": False,
            "source": "screener",
            "data": None,
            "warnings": warnings or [f"Unable to fetch Screener page for {cleaned_symbol}"],
        }

    try:
        profit_loss_html = _extract_section(html, "profit-loss")
        balance_sheet_html = _extract_section(html, "balance-sheet")
        cash_flow_html = _extract_section(html, "cash-flow")
        ratios_html = _extract_section(html, "ratios")
        shareholding_html = _extract_section(html, "shareholding")
        quarterly_html = _extract_section(html, "quarters")

        pl_rows = _parse_table(profit_loss_html)
        bs_rows = _parse_table(balance_sheet_html)
        cf_rows = _parse_table(cash_flow_html)
        ratio_rows = _parse_table(ratios_html)
        shareholding_rows = _parse_table(shareholding_html)
        quarterly_rows = _parse_table(quarterly_html)
        top_ratios = _extract_top_ratios(html)

        years = _extract_years(profit_loss_html, last_n=5)
        if not years:
            years = [f"Year {index}" for index in range(1, 6)]
            warnings.append("Could not parse fiscal year headers; using generic year labels")

        sales = _find_row(pl_rows, ["Sales", "Revenue", "Net Sales"], 5)
        operating_profit = _find_row(pl_rows, ["Operating Profit", "EBITDA"], 5)
        opm = _find_row(pl_rows, ["OPM %", "Operating Profit Margin"], 5)
        net_profit = _find_row(pl_rows, ["Net Profit", "Profit after tax", "PAT"], 5)
        eps = _find_row(pl_rows, ["EPS in Rs", "EPS"], 5)

        borrowings = _find_row(bs_rows, ["Borrowings", "Debt"], 5)
        reserves = _find_row(bs_rows, ["Reserves", "Other Equity"], 5)
        assets = _find_row(bs_rows, ["Total Assets", "Fixed Assets", "Assets"], 5)
        receivables = _find_row(bs_rows, ["Trade Receivables", "Receivables"], 5)
        contingent_liabilities = _find_row(bs_rows, ["Contingent Liabilities"], 5)

        ocf = _find_row(cf_rows, ["Cash from Operating Activity", "Operating Cash Flow", "Cash from Operations"], 5)
        capex = _find_row(cf_rows, ["Fixed Assets Purchased", "Capital Expenditure", "Capex"], 5)
        fcf = []
        if ocf and capex:
            for ocf_value, capex_value in zip(ocf, capex):
                if ocf_value is None or capex_value is None:
                    fcf.append(None)
                else:
                    # Screener often stores capex as negative cash-flow item.
                    fcf.append(ocf_value + capex_value)

        roce_series = _find_row(ratio_rows, ["ROCE %", "ROCE"], 5)
        roe_series = _find_row(ratio_rows, ["ROE %", "Return on Equity", "ROE"], 5)
        debt_equity_series = _find_row(ratio_rows, ["Debt to Equity", "Debt / Equity", "D/E"], 5)
        interest_coverage_series = _find_row(ratio_rows, ["Interest Coverage"], 5)
        current_ratio_series = _find_row(ratio_rows, ["Current Ratio"], 5)

        promoters = _find_row(shareholding_rows, ["Promoters", "Promoter"], 4)
        fii = _find_row(shareholding_rows, ["FIIs", "FII"], 4)
        dii = _find_row(shareholding_rows, ["DIIs", "DII"], 4)
        public = _find_row(shareholding_rows, ["Public"], 4)
        pledged = _find_row(shareholding_rows, ["Pledged", "Promoter Pledge"], 4)

        quarterly_sales = _find_row(quarterly_rows, ["Sales", "Revenue"], 6)
        quarterly_opm = _find_row(quarterly_rows, ["OPM %", "Operating Profit Margin"], 6)

        # ── Fallback: parse top ratios from the full HTML body if the <li> parser missed them.
        if not top_ratios.get("market_cap"):
            for label, key in [
                ("Market Cap", "market_cap"),
                ("Current Price", "current_price"),
                ("Stock P/E", "stock_p_e"),
                ("ROE", "roe"),
                ("ROCE", "roce"),
                ("Dividend Yield", "dividend_yield"),
                ("Book Value", "book_value"),
                ("Debt to equity", "debt_to_equity"),
            ]:
                if top_ratios.get(key):
                    continue
                pattern = rf"{re.escape(label)}\s*[:₹Rs.]\s*([0-9,\.\s]+(?:Cr\.|Lakh)?)"
                match = re.search(pattern, html, flags=re.I | re.S)
                if match:
                    top_ratios[key] = _to_number(match.group(1))

        data = {
            "symbol": cleaned_symbol,
            "url": final_url,
            "years": years[-5:],
            "profit_loss": {
                "sales": sales,
                "operating_profit": operating_profit,
                "opm_pct": opm,
                "net_profit": net_profit,
                "npm_pct": [
                    (np_value / sales_value * 100) if np_value is not None and sales_value not in (None, 0) else None
                    for np_value, sales_value in zip(net_profit, sales)
                ] if net_profit and sales else [],
                "eps": eps,
            },
            "balance_sheet": {
                "assets": assets,
                "borrowings": borrowings,
                "reserves": reserves,
                "receivables": receivables,
                "contingent_liabilities": contingent_liabilities,
            },
            "cash_flow": {
                "operating_cash_flow": ocf,
                "capex": capex,
                "free_cash_flow": fcf,
            },
            "ratios": {
                "roce_pct": top_ratios.get("roce") or (roce_series[-1] if roce_series else None),
                "roe_pct": top_ratios.get("roe") or (roe_series[-1] if roe_series else None),
                "debt_to_equity": top_ratios.get("debt_to_equity") or (debt_equity_series[-1] if debt_equity_series else None),
                "interest_coverage": top_ratios.get("interest_coverage") or (interest_coverage_series[-1] if interest_coverage_series else None),
                "current_ratio": top_ratios.get("current_ratio") or (current_ratio_series[-1] if current_ratio_series else None),
                "market_cap": top_ratios.get("market_cap"),
                "current_price": top_ratios.get("current_price"),
                "stock_pe": top_ratios.get("stock_p_e"),
                "dividend_yield": top_ratios.get("dividend_yield"),
            },
            "ratio_series": {
                "roce_pct": roce_series,
                "roe_pct": roe_series,
                "debt_to_equity": debt_equity_series,
                "interest_coverage": interest_coverage_series,
                "current_ratio": current_ratio_series,
            },
            "growth": {
                "sales_growth_3yr_pct": _growth_from_series(sales, 3),
                "sales_growth_5yr_pct": _growth_from_series(sales, 5),
                "profit_growth_3yr_pct": _growth_from_series(net_profit, 3),
                "profit_growth_5yr_pct": _growth_from_series(net_profit, 5),
            },
            "quarterly": {
                "sales": quarterly_sales,
                "opm_pct": quarterly_opm,
            },
            "shareholding": {
                "promoter_pct": promoters,
                "pledged_promoter_pct": pledged,
                "fii_pct": fii,
                "dii_pct": dii,
                "public_pct": public,
            },
        }

        if not sales and not net_profit:
            warnings.append("Screener page loaded, but key P&L rows were not found; page markup may have changed")

        return {"success": True, "source": "screener", "data": data, "warnings": warnings}
    except Exception as exc:
        return {
            "success": False,
            "source": "screener",
            "data": None,
            "warnings": warnings + [f"Screener parsing failed for {cleaned_symbol}: {exc}"],
        }
