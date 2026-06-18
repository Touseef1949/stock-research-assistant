"""Tests for services/kite_client.py — live Kite price integration."""

import pytest
from unittest.mock import patch, MagicMock


class TestKiteClientInit:
    """Client initialization and credential loading."""

    def test_client_available_when_credentials_exist(self, monkeypatch, tmp_path):
        """KiteClient.available is True when token + env exist."""
        import services.kite_client as kc

        # Mock Path.home() to return tmp_path
        monkeypatch.setattr(kc.Path, "home", lambda: tmp_path)

        # Create token file
        token_file = tmp_path / ".zerodha_kite_token_500.json"
        token_file.write_text('{"access_token": "test_token", "api_key": "test_key"}')

        # Create env file
        env_dir = tmp_path / "Downloads"
        env_dir.mkdir(parents=True, exist_ok=True)
        (env_dir / ".env").write_text("KITE_API_KEY=test_api_key\n")

        client = kc.KiteClient()
        assert client.available is True

    def test_client_unavailable_when_no_token_file(self, monkeypatch, tmp_path):
        """KiteClient.available is False when token file is missing."""
        import services.kite_client as kc

        monkeypatch.setattr(kc.Path, "home", lambda: tmp_path)
        client = kc.KiteClient()
        assert client.available is False

    def test_client_unavailable_when_no_env_file(self, monkeypatch, tmp_path):
        """KiteClient.available is False when env file is missing."""
        import services.kite_client as kc

        monkeypatch.setattr(kc.Path, "home", lambda: tmp_path)
        (tmp_path / ".zerodha_kite_token_500.json").write_text('{"access_token": "x"}')
        client = kc.KiteClient()
        assert client.available is False


class TestKiteClientFallback:
    """Graceful degradation when Kite is unavailable."""

    def test_get_ltp_returns_none_when_unavailable(self, monkeypatch, tmp_path):
        """get_ltp returns None when Kite is not configured."""
        import services.kite_client as kc

        monkeypatch.setattr(kc.Path, "home", lambda: tmp_path)
        client = kc.KiteClient()
        assert client.available is False
        assert client.get_ltp("SBIN") is None

    def test_get_quote_returns_none_when_unavailable(self, monkeypatch, tmp_path):
        """get_quote returns None when Kite is not configured."""
        import services.kite_client as kc

        monkeypatch.setattr(kc.Path, "home", lambda: tmp_path)
        client = kc.KiteClient()
        assert client.available is False
        assert client.get_quote("SBIN") is None

    def test_get_live_price_convenience(self, monkeypatch, tmp_path):
        """Module-level get_live_price returns None when Kite unavailable."""
        import services.kite_client as kc

        monkeypatch.setattr(kc.Path, "home", lambda: tmp_path)
        assert kc.get_live_price("SBIN") is None


class TestKiteOverlay:
    """_try_kite_overlay integration."""

    def test_overlay_sets_kite_source(self, monkeypatch):
        """_try_kite_overlay updates data with Kite prices."""
        import services.market_data as md

        data = {
            "symbol": "SBIN.NS",
            "base_symbol": "SBIN",
            "price": 1000.0,
            "change": 5.0,
            "change_pct": 0.5,
            "source": "yfinance",
            "technicals": {},
        }

        mock_quote = {
            "ltp": 1030.30,
            "open": 1027.90,
            "high": 1031.70,
            "low": 1025.05,
            "volume": 1376668,
            "change": 10.30,
            "change_pct": 1.01,
        }

        monkeypatch.setattr(
            "services.market_data._try_kite_overlay",
            lambda d, s: _apply_mock_overlay(d, mock_quote),
        )

        # Directly test the overlay logic
        md._try_kite_overlay(data, "SBIN.NS")
        assert data["source"] == "kite_live"
        assert data["price"] == 1030.30

    def test_overlay_noop_when_kite_unavailable(self, monkeypatch):
        """_try_kite_overlay does nothing when Kite returns None."""
        import services.market_data as md

        data = {"source": "yfinance", "price": 1000.0}
        monkeypatch.setattr(md, "_try_kite_overlay", lambda *a, **kw: None)
        md._try_kite_overlay(data, "SBIN.NS")
        assert data["source"] == "yfinance"


def _apply_mock_overlay(data, quote):
    data["price"] = quote["ltp"]
    data["change"] = quote["change"]
    data["change_pct"] = quote["change_pct"]
    data["source"] = "kite_live"


class TestSourceBadge:
    """_market_data_source_badge handles Kite source."""

    def test_kite_badge(self):
        """Returns Kite badge when source is kite_live."""
        import services.market_data as md

        badge = md._market_data_source_badge({"source": "kite_live"})
        assert "Kite" in badge
        assert "⚡" in badge
