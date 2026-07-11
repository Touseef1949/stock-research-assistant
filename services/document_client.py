"""Bounded retrieval and text extraction for approved research documents."""

from __future__ import annotations

from io import BytesIO
import ipaddress
import re
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from pypdf import PdfReader


APPROVED_DOCUMENT_DOMAINS = ("screener.in", "bseindia.com", "nseindia.com")
DEFAULT_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_PAGES = 25
MAX_PAGE_CONTENT_BYTES = 12 * 1024 * 1024


def _approved_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    hostname = parsed.hostname.lower().rstrip(".")
    try:
        if ipaddress.ip_address(hostname).is_private:
            return False
    except ValueError:
        pass
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in APPROVED_DOCUMENT_DOMAINS)


def _html_text(content: bytes) -> str:
    text = content.decode("utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def fetch_document_text(
    url: str,
    *,
    timeout: int = 20,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    """Fetch approved HTML/PDF research text with strict resource limits."""
    if not _approved_url(url):
        return {
            "success": False,
            "url": url,
            "text": "",
            "warnings": ["Document URL is outside the approved Screener/NSE/BSE source chain."],
        }
    try:
        current_url = url
        response = None
        for _redirect in range(4):
            response = requests.get(
                current_url,
                headers={"User-Agent": "StockResearchAssistant/1.0"},
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )
            status_code = int(getattr(response, "status_code", 200) or 200)
            location = response.headers.get("Location") if 300 <= status_code < 400 else None
            if not location:
                break
            next_url = urljoin(current_url, location)
            if not _approved_url(next_url):
                return {
                    "success": False,
                    "url": next_url,
                    "text": "",
                    "warnings": ["Document redirect left the approved source chain."],
                }
            current_url = next_url
        if response is None:
            raise RuntimeError("No document response was returned")
        response.raise_for_status()
    except Exception as exc:
        return {"success": False, "url": url, "text": "", "warnings": [f"Document fetch failed: {exc}"]}

    final_url = str(response.url or url)
    if not _approved_url(final_url):
        return {
            "success": False,
            "url": final_url,
            "text": "",
            "warnings": ["Document redirect left the approved source chain."],
        }
    declared = response.headers.get("Content-Length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        return {"success": False, "url": final_url, "text": "", "warnings": ["Document exceeds the download-size limit."]}
    if hasattr(response, "iter_content"):
        chunks = []
        size = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                return {"success": False, "url": final_url, "text": "", "warnings": ["Document exceeds the download-size limit."]}
            chunks.append(chunk)
        content = b"".join(chunks)
    else:
        content = response.content
        if len(content) > max_bytes:
            return {"success": False, "url": final_url, "text": "", "warnings": ["Document exceeds the download-size limit."]}

    content_type = response.headers.get("Content-Type", "").lower()
    is_pdf = "pdf" in content_type or final_url.lower().endswith(".pdf") or content.startswith(b"%PDF")
    if not is_pdf:
        text = _html_text(content)
        return {
            "success": bool(text),
            "url": final_url,
            "text": text[:120_000],
            "pages_read": 1,
            "truncated": len(text) > 120_000,
            "warnings": [] if text else ["No readable text was found in the document."],
        }

    warnings: list[str] = []
    try:
        reader = PdfReader(BytesIO(content), strict=False)
        parts: list[str] = []
        pages_read = 0
        for page in reader.pages[:max_pages]:
            try:
                stream = page.get_contents()
                if stream is not None and len(stream.get_data()) > MAX_PAGE_CONTENT_BYTES:
                    warnings.append(f"Skipped page {pages_read + 1}: content stream exceeded the safety limit.")
                    pages_read += 1
                    continue
                parts.append(page.extract_text() or "")
                pages_read += 1
            except Exception as exc:
                warnings.append(f"Could not extract page {pages_read + 1}: {exc}")
                pages_read += 1
        text = "\n\n".join(part.strip() for part in parts if part.strip())
        if not text:
            warnings.append("No embedded text was found; the PDF may require OCR.")
        truncated = len(reader.pages) > max_pages or len(text) > 120_000
        return {
            "success": bool(text),
            "url": final_url,
            "text": text[:120_000],
            "pages_read": pages_read,
            "total_pages": len(reader.pages),
            "truncated": truncated,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"success": False, "url": final_url, "text": "", "warnings": [f"PDF extraction failed: {exc}"]}
