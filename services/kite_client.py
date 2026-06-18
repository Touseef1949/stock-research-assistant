"""Kite Connect live-price client for Stock Research Assistant.

Provides live LTP, OHLC, and bid/ask from Zerodha Kite Connect (500-credit tier).
Uses the REST API with browser User-Agent to bypass Cloudflare 403.

Personal use only — data is for the authenticated user's own session.
Kite Connect terms prohibit public redistribution of live market data.

Usage:
    from services.kite_client import KiteClient, get_live_price

    client = KiteClient()
    price = client.get_ltp("SBIN")       # → 1029.35
    quote = client.get_quote("SBIN")     # → {ltp, open, high, low, close, volume}
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class KiteClient:
    """Lightweight Kite Connect REST client for live market data."""

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._access_token: str | None = None
        self._available: bool | None = None  # None = not checked yet
        self._load_credentials()

    def _load_credentials(self) -> None:
        """Load API key and access token from local files."""
        home = Path.home()

        # Token file
        token_file = home / ".zerodha_kite_token_500.json"
        if not token_file.exists():
            self._available = False
            return

        try:
            with open(token_file) as f:
                tok = json.load(f)
            self._access_token = tok.get("access_token", "")
        except Exception:
            self._available = False
            return

        # API key from env
        env_file = home / "Downloads" / ".env"
        try:
            for line in env_file.read_text().splitlines():
                if line.startswith("KITE_API_KEY") and "=" in line:
                    self._api_key = line.split("=", 1)[1].strip().strip("\"'")
                    break
        except Exception:
            pass

        if not self._api_key or not self._access_token:
            self._available = False
        else:
            self._available = True

    @property
    def available(self) -> bool:
        """Whether Kite credentials are configured and available."""
        if self._available is None:
            self._load_credentials()
        return self._available is True

    def _headers(self) -> dict[str, str]:
        return {
            "X-Kite-Version": "3",
            "Authorization": f"token {self._api_key}:{self._access_token}",
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
        }

    def _get(self, path: str, params: dict | None = None) -> dict:
        """Make a GET request to the Kite REST API."""
        url = f"https://api.kite.trade{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(url, headers=self._headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())

    def get_ltp(self, symbol: str) -> float | None:
        """Get last traded price for a symbol.

        Args:
            symbol: NSE symbol without prefix (e.g. 'SBIN', 'RELIANCE')

        Returns:
            Last traded price as float, or None if unavailable.
        """
        if not self.available:
            return None

        kite_symbol = f"NSE:{symbol}"
        try:
            data = self._get("/quote/ltp", {"i": kite_symbol})
            return data.get("data", {}).get(kite_symbol, {}).get("last_price")
        except Exception:
            return None

    def get_quote(self, symbol: str) -> dict[str, Any] | None:
        """Get full market depth (OHLC, bid/ask, volume) for a symbol.

        Args:
            symbol: NSE symbol without prefix (e.g. 'SBIN')

        Returns:
            Dict with keys: ltp, open, high, low, close, volume,
            bid, ask, change, change_pct. None if unavailable.
        """
        if not self.available:
            return None

        kite_symbol = f"NSE:{symbol}"
        try:
            data = self._get("/quote", {"i": kite_symbol})
            raw = data.get("data", {}).get(kite_symbol, {})
            if not raw:
                return None

            ohlc = raw.get("ohlc", {})
            depth = raw.get("depth", {})
            buy_orders = depth.get("buy", [])
            sell_orders = depth.get("sell", [])

            ltp = raw.get("last_price", 0) or 0
            close = ohlc.get("close", 0) or ltp
            change = ltp - close if close else 0.0
            change_pct = (change / close * 100) if close else 0.0

            return {
                "ltp": ltp,
                "open": ohlc.get("open"),
                "high": ohlc.get("high"),
                "low": ohlc.get("low"),
                "close": close,
                "volume": raw.get("volume"),
                "bid": buy_orders[0]["price"] if buy_orders else None,
                "ask": sell_orders[0]["price"] if sell_orders else None,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "source": "kite_live",
            }
        except Exception:
            return None

    def get_ltp_batch(self, symbols: list[str]) -> dict[str, float | None]:
        """Get LTP for multiple symbols. Falls back to per-symbol for NFO compat.

        Args:
            symbols: List of NSE symbols without prefix

        Returns:
            Dict mapping symbol → price (None for failures).
        """
        if not self.available:
            return {s: None for s in symbols}

        results: dict[str, float | None] = {}
        for sym in symbols:
            results[sym] = self.get_ltp(sym)
        return results


# Module-level singleton — reused across calls
_client: KiteClient | None = None


def get_kite_client() -> KiteClient:
    """Get or create the module-level Kite client singleton."""
    global _client
    if _client is None:
        _client = KiteClient()
    return _client


def get_live_price(symbol: str) -> float | None:
    """Convenience: get live LTP for a symbol. Returns None if Kite is unavailable."""
    return get_kite_client().get_ltp(symbol)


def get_live_quote(symbol: str) -> dict[str, Any] | None:
    """Convenience: get full quote for a symbol."""
    return get_kite_client().get_quote(symbol)
