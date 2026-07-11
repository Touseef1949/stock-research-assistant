"""Tests for external peer, filing/results, and transcript research tools."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deep_research.screener_client import _extract_document_links, _extract_peer_rows
from research_tools import external_research
from services import document_client


SCREENER_URL = "https://www.screener.in/company/TCS/consolidated/"


def screener_result() -> dict:
    return {
        "success": True,
        "source": "screener",
        "data": {
            "symbol": "TCS",
            "url": SCREENER_URL,
            "years": ["Mar 2025", "Mar 2026"],
            "profit_loss": {"sales": [100, 120], "net_profit": [20, 24]},
            "balance_sheet": {"assets": [80, 90]},
            "cash_flow": {"operating_cash_flow": [22, 26]},
            "quarterly": {"sales": [28, 30], "opm_pct": [24, 25]},
            "documents": {
                "transcripts": [
                    {
                        "title": "Q1 FY27 Concall Transcript",
                        "url": "https://www.bseindia.com/xml-data/corpfiling/transcript.pdf",
                    }
                ],
                "annual_reports": [
                    {"title": "Annual Report 2026", "url": "https://www.screener.in/annual-report.pdf"}
                ],
                "announcements": [],
            },
            "peers": [
                {
                    "S.No.": "1",
                    "Name": "Infosys",
                    "CMP Rs.": 1500.0,
                    "P/E": 25.0,
                    "source_url": "https://www.screener.in/company/INFY/",
                }
            ],
        },
        "warnings": [],
    }


def market_data() -> dict:
    return {
        "symbol": "TCS.NS",
        "source": "yfinance",
        "screener_data": screener_result(),
        "fundamentals": {},
        "technicals": {},
    }


def test_screener_parser_extracts_documents_by_category():
    html = """
    <section id="documents">
      <a href="https://www.bseindia.com/transcript.pdf">Q1 Concall Transcript</a>
      <a href="/annual-report.pdf">Annual Report 2026</a>
      <a href="https://www.nseindia.com/announcement.pdf">Exchange Announcement</a>
    </section>
    """
    documents = _extract_document_links(html, SCREENER_URL)
    assert documents["transcripts"][0]["title"] == "Q1 Concall Transcript"
    assert documents["annual_reports"][0]["url"] == "https://www.screener.in/annual-report.pdf"
    assert documents["announcements"]


def test_screener_parser_extracts_peer_rows_and_source_links():
    html = """
    <section id="peers"><table>
      <tr><th>S.No.</th><th>Name</th><th>CMP Rs.</th><th>P/E</th></tr>
      <tr><td>1</td><td><a href="/company/INFY/">Infosys</a></td><td>1,500</td><td>25</td></tr>
      <tr><td>2</td><td>Median</td><td>1,400</td><td>24</td></tr>
    </table></section>
    """
    peers = _extract_peer_rows(html, SCREENER_URL)
    assert len(peers) == 1
    assert peers[0]["Name"] == "Infosys"
    assert peers[0]["P/E"] == 25.0
    assert peers[0]["source_url"] == "https://www.screener.in/company/INFY/"


def test_filing_results_normalizes_structured_financials():
    result = external_research.get_filing_results(market_data())
    assert result.success is True
    assert result.source == "screener"
    assert result.confidence == "high"
    assert result.data["quarterly_results"]["sales"] == [28, 30]
    assert any(item.metric == "profit_loss" for item in result.evidence)


def test_peer_metrics_uses_public_screener_peer_table():
    result = external_research.get_peer_metrics(market_data())
    assert result.success is True
    assert result.source == "screener"
    assert result.data["peers"][0]["Name"] == "Infosys"
    assert any(item.metric == "peers" for item in result.evidence)


def test_peer_metrics_excludes_target_security_from_comparables():
    data = market_data()
    data["screener_data"]["data"]["peers"].insert(
        0,
        {"Name": "TCS", "source_url": "https://www.screener.in/company/TCS/consolidated/"},
    )
    result = external_research.get_peer_metrics(data)
    assert [peer["Name"] for peer in result.data["peers"]] == ["Infosys"]


def test_transcript_tool_fetches_latest_approved_document(monkeypatch):
    monkeypatch.setattr(
        external_research,
        "fetch_document_text",
        lambda url: {
            "success": True,
            "url": url,
            "text": "Management discussed demand, margins, and guidance.",
            "pages_read": 12,
            "truncated": False,
            "warnings": [],
        },
    )
    result = external_research.get_earnings_transcript(market_data())
    assert result.success is True
    assert result.data["pages_read"] == 12
    assert "guidance" in result.data["text"]
    assert result.evidence[0].source_url.endswith("transcript.pdf")


def test_transcript_tool_returns_specific_gap_when_link_missing():
    data = market_data()
    data["screener_data"]["data"]["documents"]["transcripts"] = []
    result = external_research.get_earnings_transcript(data)
    assert result.success is False
    assert any("No earnings transcript link" in warning for warning in result.warnings)


def test_document_client_rejects_unapproved_or_insecure_urls():
    assert document_client.fetch_document_text("http://www.bseindia.com/file.pdf")["success"] is False
    assert document_client.fetch_document_text("https://127.0.0.1/file.pdf")["success"] is False
    assert document_client.fetch_document_text("https://example.com/file.pdf")["success"] is False


def test_document_client_extracts_bounded_html(monkeypatch):
    response = SimpleNamespace(
        url="https://www.screener.in/document/1/",
        headers={"Content-Type": "text/html", "Content-Length": "45"},
        content=b"<html><body><h1>Concall</h1><p>Guidance raised.</p></body></html>",
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(document_client.requests, "get", lambda *args, **kwargs: response)
    result = document_client.fetch_document_text(response.url)
    assert result["success"] is True
    assert "Guidance raised" in result["text"]


def test_document_client_enforces_declared_size_limit(monkeypatch):
    response = SimpleNamespace(
        url="https://www.bseindia.com/file.pdf",
        headers={"Content-Type": "application/pdf", "Content-Length": "99999999"},
        content=b"",
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(document_client.requests, "get", lambda *args, **kwargs: response)
    result = document_client.fetch_document_text(response.url, max_bytes=100)
    assert result["success"] is False
    assert "size limit" in result["warnings"][0]


def test_document_client_rejects_redirect_outside_approved_chain(monkeypatch):
    response = SimpleNamespace(
        url="https://www.bseindia.com/file.pdf",
        status_code=302,
        headers={"Location": "https://example.com/untrusted.pdf"},
        content=b"",
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(document_client.requests, "get", lambda *args, **kwargs: response)
    result = document_client.fetch_document_text(response.url)
    assert result["success"] is False
    assert "redirect" in result["warnings"][0].lower()


def test_document_client_stream_cap_stops_oversized_body(monkeypatch):
    response = SimpleNamespace(
        url="https://www.bseindia.com/file.pdf",
        status_code=200,
        headers={"Content-Type": "application/pdf"},
        content=b"",
        iter_content=lambda chunk_size: iter([b"a" * 60, b"b" * 60]),
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(document_client.requests, "get", lambda *args, **kwargs: response)
    result = document_client.fetch_document_text(response.url, max_bytes=100)
    assert result["success"] is False
    assert "size limit" in result["warnings"][0]


def test_financial_fetch_cache_avoids_duplicate_external_calls(monkeypatch):
    calls = []
    external_research.clear_external_tool_cache()
    monkeypatch.setattr(
        external_research,
        "fetch_screener_financials",
        lambda symbol: calls.append(symbol) or screener_result(),
    )
    data = {"symbol": "TCS.NS", "fundamentals": {}, "technicals": {}}
    external_research.get_filing_results(data)
    external_research.get_peer_metrics(data)
    assert calls == ["TCS.NS"]


def test_analyst_consensus_uses_embedded_market_info_without_network(monkeypatch):
    monkeypatch.setattr(
        external_research,
        "fetch_analyst_targets",
        lambda _symbol: (_ for _ in ()).throw(AssertionError("network fallback should not run")),
    )
    data = market_data()
    data["price"] = 4000
    data["info"] = {
        "targetMeanPrice": 4400,
        "targetHighPrice": 5000,
        "targetLowPrice": 3500,
        "numberOfAnalystOpinions": 20,
        "recommendationKey": "buy",
    }
    result = external_research.get_analyst_consensus(data)
    assert result.success is True
    assert result.data["upside_downside_pct"] == pytest.approx(10)
    assert any(item.metric == "target_mean_price" for item in result.evidence)


def test_recent_news_normalizes_current_yfinance_shape(monkeypatch):
    monkeypatch.setattr(
        external_research,
        "ticker_news",
        lambda symbol, count=10: [
            {
                "content": {
                    "title": "TCS announces new contract",
                    "provider": {"displayName": "Exchange News"},
                    "pubDate": "2026-07-11T10:00:00Z",
                    "summary": "The company announced a material contract.",
                    "canonicalUrl": {"url": "https://finance.yahoo.com/news/tcs-contract"},
                }
            }
        ],
    )
    result = external_research.get_recent_news({"symbol": "TCS.NS"})
    assert result.success is True
    assert result.data["items"][0]["publisher"] == "Exchange News"
    assert result.evidence[0].source_url.endswith("tcs-contract")
