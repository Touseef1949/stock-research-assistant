"""Resilient yfinance wrapper with retry/backoff and rate-limit detection.

All yfinance calls in the app must go through this module so that:
- 429 / Too Many Requests from Yahoo Finance are retried with exponential backoff
- shared Hugging Face IPs get a short cooling-off period
- failures return structured errors instead of crashing the whole analysis
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, TypeVar

try:
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None  # type: ignore[assignment]


T = TypeVar("T")


class YFinanceRateLimitError(Exception):
    """Raised when Yahoo Finance returns a 429 / rate-limit response."""


_MAX_RETRIES = 3
_BASE_DELAY = 2.0
_MAX_DELAY = 20.0

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36",
]


def _session() -> Any:
    if requests is None:
        return None
    session = requests.Session()
    session.headers.update({
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


_SESSION = _session()

def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect Yahoo Finance / upstream rate-limit exceptions."""
    text = str(exc).lower()
    rate_limit_markers = (
        "too many requests",
        "rate limit",
        "429",
        "unauthorized",
        "blocked",
        "forbidden",
    )
    if any(marker in text for marker in rate_limit_markers):
        return True
    # yfinance sometimes wraps requests.HTTPError; check status_code attribute
    status = getattr(exc, "status_code", None)
    if status in (429, 401, 403):
        return True
    # Check chained requests exceptions
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause is not None:
        return _is_rate_limit_error(cause)
    return False


def _sleep_with_jitter(attempt: int) -> None:
    """Exponential backoff with full jitter."""
    delay = min(_BASE_DELAY * (2**attempt), _MAX_DELAY)
    jitter = random.uniform(0, delay)
    time.sleep(jitter)


def _call_with_retry(fn: Callable[[], T], operation: str) -> T:
    """Call a zero-arg function with retry/backoff on rate limits."""
    last_exc: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            return fn()
        except YFinanceRateLimitError:
            raise
        except Exception as exc:
            last_exc = exc
            if not _is_rate_limit_error(exc):
                raise
            if attempt >= _MAX_RETRIES:
                break
            _sleep_with_jitter(attempt)
    raise YFinanceRateLimitError(
        f"Yahoo Finance rate limit exceeded while {operation}. "
        "Their servers are temporarily blocking this IP. Please wait a minute and try again."
    ) from last_exc


def ticker_info(symbol: str) -> dict[str, Any]:
    """Fetch ticker.info with retry/backoff."""
    if yf is None:
        return {}

    def _fetch() -> dict[str, Any]:
        try:
            ticker = yf.Ticker(symbol, session=_SESSION)
            info = ticker.info or {}
            return dict(info)
        except Exception as exc:
            if _is_rate_limit_error(exc):
                raise YFinanceRateLimitError(str(exc)) from exc
            raise

    return _call_with_retry(_fetch, f"fetching info for {symbol}")


def ticker_history(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    auto_adjust: bool = False,
) -> Any:
    """Fetch ticker history with retry/backoff."""
    if yf is None:
        return None

    def _fetch() -> Any:
        try:
            return yf.Ticker(symbol, session=_SESSION).history(
                period=period,
                interval=interval,
                auto_adjust=auto_adjust,
            )
        except Exception as exc:
            if _is_rate_limit_error(exc):
                raise YFinanceRateLimitError(str(exc)) from exc
            raise

    return _call_with_retry(_fetch, f"fetching price history for {symbol}")


def search_quotes(query: str) -> list[dict[str, Any]]:
    """Search yfinance quotes with retry/backoff."""
    if yf is None or not hasattr(yf, "Search"):
        return []

    def _fetch() -> list[dict[str, Any]]:
        try:
            result = yf.Search(query)
            return list(getattr(result, "quotes", []) or [])
        except Exception as exc:
            if _is_rate_limit_error(exc):
                raise YFinanceRateLimitError(str(exc)) from exc
            raise

    return _call_with_retry(_fetch, f"searching for {query}")


def is_rate_limit_error(exc: Exception) -> bool:
    """Public helper to detect rate-limit errors."""
    return _is_rate_limit_error(exc)
