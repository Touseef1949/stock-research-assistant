"""External research adapters for peers, filings/results, and transcripts."""

from __future__ import annotations

from copy import deepcopy
from time import monotonic
from typing import Any, Callable

from core.research_contracts import Evidence, ToolResult, utc_now_iso
from deep_research.peer_analysis import build_peer_comparison
from deep_research.analyst_targets import fetch_analyst_targets
from deep_research.screener_client import fetch_screener_financials
from services.document_client import fetch_document_text
from yf_client import ticker_news

_CACHE_TTL_SECONDS = 900
_financial_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def clear_external_tool_cache() -> None:
    _financial_cache.clear()


def _symbol(data: dict[str, Any]) -> str:
    return str(data.get("symbol") or data.get("base_symbol") or "").strip().upper()


def _financials(data: dict[str, Any]) -> dict[str, Any]:
    embedded = data.get("screener_data")
    if isinstance(embedded, dict) and embedded.get("success"):
        return embedded
    symbol = _symbol(data)
    cached = _financial_cache.get(symbol)
    if cached and monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return deepcopy(cached[1])
    result = fetch_screener_financials(symbol)
    _financial_cache[symbol] = (monotonic(), deepcopy(result))
    return result


def _evidence(
    symbol: str,
    tool: str,
    source: str,
    source_url: str,
    values: dict[str, Any],
    confidence: str,
) -> list[Evidence]:
    as_of = utc_now_iso()
    return [
        Evidence(
            evidence_id=f"{symbol or 'UNKNOWN'}-{tool}-{index:03d}",
            metric=key,
            value=value,
            source=source,
            source_url=source_url,
            as_of=as_of,
            confidence=confidence,
            kind="reported",
        )
        for index, (key, value) in enumerate(values.items(), start=1)
        if value not in (None, [], {})
    ]


def get_filing_results(data: dict[str, Any]) -> ToolResult:
    symbol = _symbol(data)
    result = _financials(data)
    payload = result.get("data") if isinstance(result.get("data"), dict) else {}
    source = str(result.get("source") or "screener")
    source_url = str(payload.get("url") or "")
    values = {
        "fiscal_years": payload.get("years"),
        "quarterly_results": payload.get("quarterly"),
        "profit_loss": payload.get("profit_loss"),
        "balance_sheet": payload.get("balance_sheet"),
        "cash_flow": payload.get("cash_flow"),
        "annual_reports": (payload.get("documents") or {}).get("annual_reports"),
        "announcements": (payload.get("documents") or {}).get("announcements"),
    }
    success = bool(
        result.get("success")
        and any(values.get(key) for key in ("quarterly_results", "profit_loss"))
    )
    confidence = "high" if source == "screener" and success else "medium" if success else "low"
    warnings = [str(item) for item in result.get("warnings") or []]
    if not success:
        warnings.append("No structured filing/results data was available for this security.")
    return ToolResult(
        tool_name="get_filing_results",
        success=success,
        symbol=symbol,
        source=source,
        data={**values, "source_url": source_url},
        evidence=_evidence(symbol, "get_filing_results", source, source_url, values, confidence),
        confidence=confidence,
        is_fallback=source != "screener",
        warnings=list(dict.fromkeys(warnings)),
    )


def get_peer_metrics(data: dict[str, Any]) -> ToolResult:
    symbol = _symbol(data)
    financials = _financials(data)
    payload = financials.get("data") if isinstance(financials.get("data"), dict) else {}
    source_url = str(payload.get("url") or "")
    screener_peers = payload.get("peers") if isinstance(payload.get("peers"), list) else []
    base_symbol = symbol.removesuffix(".NS").removesuffix(".BO")
    screener_peers = [
        peer
        for peer in screener_peers
        if f"/COMPANY/{base_symbol}/" not in str(peer.get("source_url") or "").upper()
    ]
    peer_tickers = data.get("peer_tickers") or []
    warnings = [str(item) for item in financials.get("warnings") or []]

    if peer_tickers:
        comparison = build_peer_comparison(symbol, peer_tickers, data, financials)
        comparison_data = comparison.get("data") if isinstance(comparison.get("data"), dict) else {}
        values = {
            "target": comparison_data.get("target"),
            "peers": comparison_data.get("peers"),
            "peer_stats": comparison_data.get("peer_stats"),
            "valuation_flags": comparison_data.get("valuation_flags"),
        }
        warnings.extend(str(item) for item in comparison.get("warnings") or [])
        source = str(comparison.get("source") or "yfinance")
        success = bool(comparison_data.get("peers"))
    else:
        values = {"peers": screener_peers}
        source = "screener"
        success = bool(screener_peers)
        if not success:
            warnings.append(
                "No public peer table was found; supply peer_tickers for a targeted comparison."
            )

    confidence = "high" if success and source == "screener" else "medium" if success else "low"
    return ToolResult(
        tool_name="get_peer_metrics",
        success=success,
        symbol=symbol,
        source=source,
        data={**values, "source_url": source_url},
        evidence=_evidence(symbol, "get_peer_metrics", source, source_url, values, confidence),
        confidence=confidence,
        is_fallback=source != "screener",
        warnings=list(dict.fromkeys(warnings)),
    )


def get_earnings_transcript(data: dict[str, Any]) -> ToolResult:
    symbol = _symbol(data)
    financials = _financials(data)
    payload = financials.get("data") if isinstance(financials.get("data"), dict) else {}
    documents = payload.get("documents") if isinstance(payload.get("documents"), dict) else {}
    transcripts = (
        documents.get("transcripts") if isinstance(documents.get("transcripts"), list) else []
    )
    warnings = [str(item) for item in financials.get("warnings") or []]
    if not transcripts:
        warnings.append(
            "No earnings transcript link was found on the public company documents page."
        )
        return ToolResult(
            tool_name="get_earnings_transcript",
            success=False,
            symbol=symbol,
            source="screener",
            data={"transcripts": [], "source_url": str(payload.get("url") or "")},
            confidence="low",
            warnings=list(dict.fromkeys(warnings)),
        )

    transcript_documents = [
        item for item in transcripts if "transcript" in str(item.get("title") or "").lower()
    ]
    latest = (transcript_documents or transcripts)[0]
    document = fetch_document_text(str(latest.get("url") or ""))
    warnings.extend(str(item) for item in document.get("warnings") or [])
    values = {
        "title": latest.get("title"),
        "url": document.get("url") or latest.get("url"),
        "text": document.get("text"),
        "pages_read": document.get("pages_read"),
        "truncated": document.get("truncated", False),
        "available_transcripts": transcripts,
    }
    success = bool(document.get("success") and document.get("text"))
    confidence = "high" if success else "medium"
    return ToolResult(
        tool_name="get_earnings_transcript",
        success=success,
        symbol=symbol,
        source="screener_document",
        data=values,
        evidence=_evidence(
            symbol,
            "get_earnings_transcript",
            "screener_document",
            str(values["url"] or ""),
            values,
            confidence,
        ),
        confidence=confidence,
        warnings=list(dict.fromkeys(warnings)),
    )


def get_analyst_consensus(data: dict[str, Any]) -> ToolResult:
    symbol = _symbol(data)
    info = data.get("info") if isinstance(data.get("info"), dict) else {}
    if any(
        key in info for key in ("targetMeanPrice", "numberOfAnalystOpinions", "recommendationKey")
    ):
        current_price = (
            info.get("currentPrice") or info.get("regularMarketPrice") or data.get("price")
        )
        target_mean = info.get("targetMeanPrice")
        try:
            upside = (
                ((float(target_mean) / float(current_price)) - 1) * 100
                if target_mean and current_price
                else None
            )
        except (TypeError, ValueError, ZeroDivisionError):
            upside = None
        payload = {
            "symbol": symbol,
            "current_price": current_price,
            "target_mean_price": target_mean,
            "target_high_price": info.get("targetHighPrice"),
            "target_low_price": info.get("targetLowPrice"),
            "number_of_analyst_opinions": info.get("numberOfAnalystOpinions") or 0,
            "recommendation_key": info.get("recommendationKey") or "unavailable",
            "recommendation_mean": info.get("recommendationMean"),
            "upside_downside_pct": upside,
        }
        result = {
            "success": True,
            "source": "yfinance",
            "data": payload,
            "warnings": [],
        }
    else:
        result = fetch_analyst_targets(symbol)
        payload = result.get("data") if isinstance(result.get("data"), dict) else {}
    opinions = int(payload.get("number_of_analyst_opinions") or 0)
    success = bool(result.get("success") and opinions > 0)
    warnings = [str(item) for item in result.get("warnings") or []]
    if not success and not warnings:
        warnings.append("No usable analyst consensus was available for this security.")
    confidence = "medium" if success else "low"
    return ToolResult(
        tool_name="get_analyst_consensus",
        success=success,
        symbol=symbol,
        source="yfinance",
        data=payload,
        evidence=_evidence(symbol, "get_analyst_consensus", "yfinance", "", payload, confidence),
        confidence=confidence,
        warnings=list(dict.fromkeys(warnings)),
    )


def _normalize_news_item(item: dict[str, Any]) -> dict[str, Any] | None:
    content = item.get("content") if isinstance(item.get("content"), dict) else item
    provider = content.get("provider") if isinstance(content.get("provider"), dict) else {}
    canonical = content.get("canonicalUrl") if isinstance(content.get("canonicalUrl"), dict) else {}
    clickthrough = (
        content.get("clickThroughUrl") if isinstance(content.get("clickThroughUrl"), dict) else {}
    )
    title = str(content.get("title") or item.get("title") or "").strip()
    if not title:
        return None
    return {
        "title": title,
        "publisher": provider.get("displayName") or item.get("publisher") or "Unknown",
        "published_at": content.get("pubDate") or item.get("providerPublishTime"),
        "summary": content.get("summary") or content.get("description") or "",
        "url": canonical.get("url") or clickthrough.get("url") or item.get("link") or "",
    }


def get_recent_news(data: dict[str, Any]) -> ToolResult:
    symbol = _symbol(data)
    warnings: list[str] = []
    try:
        raw_items = (
            data.get("news")
            if isinstance(data.get("news"), list)
            else ticker_news(symbol, count=10)
        )
    except Exception as exc:
        raw_items = []
        warnings.append(f"Recent news retrieval failed: {exc}")
    items = [
        normalized
        for item in raw_items
        if isinstance(item, dict)
        if (normalized := _normalize_news_item(item))
    ]
    if not items:
        warnings.append("No recent structured news items were available for this security.")
    evidence = [
        Evidence(
            evidence_id=f"{symbol or 'UNKNOWN'}-get_recent_news-{index:03d}",
            metric="news_item",
            value={
                "title": item["title"],
                "publisher": item["publisher"],
                "published_at": item["published_at"],
            },
            source="yfinance_news",
            source_url=str(item.get("url") or ""),
            as_of=utc_now_iso(),
            confidence="medium",
            kind="reported",
        )
        for index, item in enumerate(items, start=1)
    ]
    return ToolResult(
        tool_name="get_recent_news",
        success=bool(items),
        symbol=symbol,
        source="yfinance_news",
        data={"items": items},
        evidence=evidence,
        confidence="medium" if items else "low",
        warnings=list(dict.fromkeys(warnings)),
    )


EXTERNAL_TOOL_FUNCTIONS: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
    "get_peer_metrics": get_peer_metrics,
    "get_filing_results": get_filing_results,
    "get_earnings_transcript": get_earnings_transcript,
    "get_analyst_consensus": get_analyst_consensus,
    "get_recent_news": get_recent_news,
}
