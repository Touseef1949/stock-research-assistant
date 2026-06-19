import json

import logic
from services import symbol_master


EQUITY_CSV = """SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
EIEL,Enviro Infra Engineers Limited,EQ,29-NOV-2024,10,1,INE0LLY01014,10
BALUFORGE,Balu Forge Industries Limited,EQ,29-APR-2024,10,1,INE011E01029,10
360ONE,360 ONE WAM LIMITED,EQ,21-SEP-2019,1,1,INE466L01038,1
"""

NAME_CHANGE_CSV = """NCH_SYMBOL, NCH_PREV_NAME, NCH_NEW_NAME, NCH_DT
EIEL,Enviro Infra Engineers Pvt Ltd,Enviro Infra Engineers Limited,29-NOV-2024
"""

SYMBOL_CHANGE_CSV = """360 ONE WAM LIMITED,IIFLWAM,360ONE,23-JAN-2023
"""


def _write_cache(path, generated_at=4_000_000_000):
    data = {
        "schema_version": 1,
        "generated_at": generated_at,
        "records": [
            {
                "symbol": "EIEL",
                "name": "Enviro Infra Engineers Limited",
                "series": "EQ",
                "isin": "INE0LLY01014",
                "aliases": [],
                "previous_symbols": [],
            },
            {
                "symbol": "BALUFORGE",
                "name": "Balu Forge Industries Limited",
                "series": "EQ",
                "isin": "INE011E01029",
                "aliases": [],
                "previous_symbols": [],
            },
            {
                "symbol": "360ONE",
                "name": "360 ONE WAM LIMITED",
                "series": "EQ",
                "isin": "INE466L01038",
                "aliases": [],
                "previous_symbols": ["IIFLWAM"],
            },
        ],
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_symbol_master_exact_symbol_and_company_name_matches(tmp_path):
    cache_path = tmp_path / "symbol_master_nse.json"
    _write_cache(cache_path)

    by_symbol = symbol_master.resolve_from_symbol_master("EIEL", cache_path=cache_path, refresh=False)
    by_name = symbol_master.resolve_from_symbol_master(
        "Enviro Infra Engineers Limited",
        cache_path=cache_path,
        refresh=False,
    )

    assert by_symbol == {
        "symbol": "EIEL.NS",
        "name": "Enviro Infra Engineers Limited",
        "source": "symbol_master_symbol",
    }
    assert by_name["symbol"] == "EIEL.NS"
    assert by_name["source"] == "symbol_master_name"


def test_symbol_master_stripped_legal_suffix_matches(tmp_path):
    cache_path = tmp_path / "symbol_master_nse.json"
    _write_cache(cache_path)

    eiel = symbol_master.resolve_from_symbol_master("EIEL Limited", cache_path=cache_path, refresh=False)
    balu = symbol_master.resolve_from_symbol_master("Balu Forge", cache_path=cache_path, refresh=False)

    assert eiel["symbol"] == "EIEL.NS"
    assert eiel["source"] == "symbol_master_stripped"
    assert balu["symbol"] == "BALUFORGE.NS"
    assert balu["source"] in {"symbol_master_symbol", "symbol_master_stripped"}


def test_symbol_master_official_csv_refresh_and_symbol_change_alias(tmp_path, monkeypatch):
    cache_path = tmp_path / "symbol_master_nse.json"

    def fake_fetch(url):
        if url == symbol_master.EQUITY_MASTER_URL:
            return EQUITY_CSV
        if url == symbol_master.NAME_CHANGE_URL:
            return NAME_CHANGE_CSV
        if url == symbol_master.SYMBOL_CHANGE_URL:
            return SYMBOL_CHANGE_CSV
        raise AssertionError(url)

    monkeypatch.setattr(symbol_master, "_fetch_url", fake_fetch)

    symbol_master.refresh_symbol_master(cache_path)
    result = symbol_master.resolve_from_symbol_master("IIFLWAM", cache_path=cache_path, refresh=False)

    assert result["symbol"] == "360ONE.NS"
    assert result["name"] == "360 ONE WAM LIMITED"
    assert result["source"] == "symbol_master_symbol"


def test_symbol_master_stale_cache_used_when_refresh_fails(tmp_path, monkeypatch):
    cache_path = tmp_path / "symbol_master_nse.json"
    _write_cache(cache_path, generated_at=1)

    def fail_refresh(path):
        raise OSError("network unavailable")

    monkeypatch.setattr(symbol_master, "refresh_symbol_master", fail_refresh)

    data = symbol_master.load_symbol_master(cache_path=cache_path, ttl_seconds=0, refresh=True)
    result = symbol_master.resolve_from_symbol_master("EIEL", cache_path=cache_path, refresh=True)

    assert data is not None
    assert result["symbol"] == "EIEL.NS"


def test_symbol_master_garbage_stays_unresolved(tmp_path):
    cache_path = tmp_path / "symbol_master_nse.json"
    _write_cache(cache_path)

    result = symbol_master.resolve_from_symbol_master(
        "zzzxyznonexistent",
        cache_path=cache_path,
        refresh=False,
    )

    assert result["symbol"] == ""
    assert result["source"] == "unknown"


def test_symbol_master_suggestions_include_best_matches(tmp_path):
    cache_path = tmp_path / "symbol_master_nse.json"
    _write_cache(cache_path)

    suggestions = symbol_master.suggest_from_symbol_master(
        "EIEL Limited",
        cache_path=cache_path,
        refresh=False,
        limit=3,
    )

    assert suggestions
    assert suggestions[0]["symbol"] == "EIEL.NS"
    assert suggestions[0]["name"] == "Enviro Infra Engineers Limited"


def test_resolve_ticker_uses_symbol_master_before_yfinance(monkeypatch):
    monkeypatch.setattr(
        logic,
        "resolve_from_symbol_master",
        lambda text: {
            "symbol": "EIEL.NS",
            "name": "Enviro Infra Engineers Limited",
            "source": "symbol_master_name",
        },
    )
    monkeypatch.setattr(logic, "_validate_ticker", lambda symbol: False)
    monkeypatch.setattr(
        logic,
        "_search_yfinance",
        lambda query: {"symbol": "WRONG.NS", "name": "Wrong", "source": "search"},
    )

    result = logic.resolve_ticker("Enviro Infra Engineers Limited")

    assert result["symbol"] == "EIEL.NS"
    assert result["source"] == "symbol_master_name"


def test_resolve_ticker_falls_back_to_old_path_when_symbol_master_unavailable(monkeypatch):
    monkeypatch.setattr(
        logic,
        "resolve_from_symbol_master",
        lambda text: {"symbol": "", "name": "", "source": "unknown"},
    )
    monkeypatch.setattr(logic, "_validate_ticker", lambda symbol: False)
    monkeypatch.setattr(
        logic,
        "_search_yfinance",
        lambda query: {"symbol": "BALUFORGE.NS", "name": "Balu Forge", "source": "search"},
    )

    result = logic.resolve_ticker("Balu Forge")

    assert result["symbol"] == "BALUFORGE.NS"
    assert result["source"] == "search"
