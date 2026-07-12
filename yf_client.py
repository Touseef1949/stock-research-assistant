"""Resilient yfinance wrapper with retry/backoff and rate-limit detection.

All yfinance calls in the app must go through this module so that:
- 429 / Too Many Requests from Yahoo Finance are retried with exponential backoff
- shared Hugging Face IPs get a cooling-off period
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


_MAX_RETRIES = 4
_BASE_DELAY = 3.0
_MAX_DELAY = 30.0

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
]


def _fresh_session() -> Any:
    """Build a brand-new requests session for each yfinance call.

    Reusing a session after a 429 can keep the blocked crumb/cookie state.
    Fresh sessions give each attempt the best chance of passing Yahoo's front door.
    """
    if requests is None:
        return None
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        }
    )
    return session


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect Yahoo Finance / upstream rate-limit exceptions."""
    text = str(exc).lower()
    rate_limit_markers = (
        "too many requests",
        "rate limit",
        "rate limited",
        "429",
        "unauthorized",
        "blocked",
        "forbidden",
        "yfratelimiterror",
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
    """Exponential backoff with full jitter.

    Attempt 0: 0-3s, attempt 1: 0-6s, attempt 2: 0-12s, attempt 3: 0-24s, attempt 4: 0-30s
    """
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
    """Fetch ticker.info with retry/backoff and a fresh session per attempt."""
    if yf is None:
        return {}

    def _fetch() -> dict[str, Any]:
        try:
            ticker = yf.Ticker(symbol, session=_fresh_session())
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
    """Fetch ticker history with retry/backoff and a fresh session per attempt."""
    if yf is None:
        return None

    def _fetch() -> Any:
        try:
            return yf.Ticker(symbol, session=_fresh_session()).history(
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


def ticker_news(symbol: str, count: int = 10) -> list[dict[str, Any]]:
    """Fetch recent yfinance news through the shared retry/rate-limit policy."""
    if yf is None:
        return []

    def _fetch() -> list[dict[str, Any]]:
        try:
            ticker = yf.Ticker(symbol, session=_fresh_session())
            if hasattr(ticker, "get_news"):
                return list(ticker.get_news(count=count) or [])[:count]
            return list(getattr(ticker, "news", []) or [])[:count]
        except Exception as exc:
            if _is_rate_limit_error(exc):
                raise YFinanceRateLimitError(str(exc)) from exc
            raise

    return _call_with_retry(_fetch, f"fetching news for {symbol}")


def is_rate_limit_error(exc: Exception) -> bool:
    """Public helper to detect rate-limit errors."""
    return _is_rate_limit_error(exc)
