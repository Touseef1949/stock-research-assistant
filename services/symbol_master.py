"""Cached NSE symbol-master resolver.

Uses official NSE downloadable CSVs as the public master source and keeps a
local JSON cache under the repository for fast, offline-friendly resolution.
"""

from __future__ import annotations

import csv
import difflib
import io
import json
import re
import time
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = PROJECT_ROOT / "data" / "symbol_master_nse.json"
CACHE_TTL_SECONDS = 24 * 60 * 60

EQUITY_MASTER_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
NAME_CHANGE_URL = "https://nsearchives.nseindia.com/content/equities/namechange.csv"
SYMBOL_CHANGE_URL = "https://nsearchives.nseindia.com/content/equities/symbolchange.csv"

EQUITY_MASTER_HEADER = [
    "SYMBOL",
    "NAME OF COMPANY",
    " SERIES",
    " DATE OF LISTING",
    " PAID UP VALUE",
    " MARKET LOT",
    " ISIN NUMBER",
    " FACE VALUE",
]
NAME_CHANGE_HEADER = ["NCH_SYMBOL", " NCH_PREV_NAME", " NCH_NEW_NAME", " NCH_DT"]

LEGAL_SUFFIXES = {
    "LIMITED",
    "LTD",
    "INDUSTRIES",
    "INDUSTRY",
    "ENGINEERS",
    "ENGINEER",
    "ENGINEERING",
    "COMPANY",
    "CO",
    "CORPORATION",
    "CORP",
    "PRIVATE",
    "PVT",
    "PUBLIC",
    "PLC",
    "INC",
    "INCORPORATED",
}
OPTIONAL_STRIP_SUFFIXES = {"INDIA"}


def normalize_key(value: str) -> str:
    """Uppercase and remove punctuation/spaces for matching."""
    clean = re.sub(r"\.(NS|NSE|BSE|BO)$", "", str(value or "").upper().strip())
    return re.sub(r"[^A-Z0-9]", "", clean)


def stripped_name_key(value: str) -> str:
    """Normalize after removing common legal suffix words from the end."""
    words = re.findall(r"[A-Z0-9]+", str(value or "").upper())
    suffixes = LEGAL_SUFFIXES | OPTIONAL_STRIP_SUFFIXES
    while words and words[-1] in suffixes:
        words.pop()
    return normalize_key(" ".join(words))


def _empty_result() -> dict[str, str]:
    return {"symbol": "", "name": "", "source": "unknown"}


def _ticker_result(symbol: str, name: str, source: str) -> dict[str, str]:
    nse_symbol = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
    return {"symbol": nse_symbol, "name": name or symbol, "source": source}


def _fetch_url(url: str, timeout: int = 10) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/csv,*/*",
            "Referer": "https://www.nseindia.com/",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8-sig", errors="replace")


def _parse_equity_master(csv_text: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames != EQUITY_MASTER_HEADER:
        raise ValueError(f"Unexpected NSE equity master header: {reader.fieldnames!r}")

    records: list[dict[str, Any]] = []
    for row in reader:
        symbol = str(row.get("SYMBOL", "")).strip().upper()
        name = str(row.get("NAME OF COMPANY", "")).strip()
        series = str(row.get(" SERIES", "")).strip().upper()
        if not symbol or not name:
            continue
        records.append(
            {
                "symbol": symbol,
                "name": name,
                "series": series,
                "isin": str(row.get(" ISIN NUMBER", "")).strip(),
                "aliases": [],
                "previous_symbols": [],
            }
        )
    return records


def _parse_name_changes(csv_text: str) -> dict[str, list[str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    if reader.fieldnames != NAME_CHANGE_HEADER:
        raise ValueError(f"Unexpected NSE name-change header: {reader.fieldnames!r}")

    aliases: dict[str, list[str]] = {}
    for row in reader:
        symbol = str(row.get("NCH_SYMBOL", "")).strip().upper()
        if not symbol:
            continue
        names = [
            str(row.get(" NCH_PREV_NAME", "")).strip(),
            str(row.get(" NCH_NEW_NAME", "")).strip(),
        ]
        aliases.setdefault(symbol, [])
        for name in names:
            if name and name not in aliases[symbol]:
                aliases[symbol].append(name)
    return aliases


def _parse_symbol_changes(csv_text: str) -> dict[str, str]:
    changes: dict[str, str] = {}
    reader = csv.reader(io.StringIO(csv_text))
    for row in reader:
        if len(row) < 4:
            continue
        company_name, old_symbol, new_symbol, _date = [col.strip() for col in row[:4]]
        if old_symbol.upper() in {"OLD_SYMBOL", "OLD SYMBOL", "SYMBOL"}:
            continue
        if company_name.upper() in {"COMPANY_NAME", "COMPANY NAME"}:
            continue
        old_key = old_symbol.upper()
        new_key = new_symbol.upper()
        if old_key and new_key and old_key != new_key:
            changes[old_key] = new_key
    return changes


def _apply_aliases(
    records: list[dict[str, Any]],
    name_aliases: dict[str, list[str]],
    symbol_changes: dict[str, str],
) -> list[dict[str, Any]]:
    by_symbol = {record["symbol"]: record for record in records}

    for symbol, aliases in name_aliases.items():
        record = by_symbol.get(symbol)
        if not record:
            continue
        for alias in aliases:
            if alias and alias not in record["aliases"]:
                record["aliases"].append(alias)

    for old_symbol, new_symbol in symbol_changes.items():
        record = by_symbol.get(new_symbol)
        if not record:
            continue
        if old_symbol not in record["previous_symbols"]:
            record["previous_symbols"].append(old_symbol)

    return records


def refresh_symbol_master(cache_path: Path = CACHE_PATH) -> dict[str, Any]:
    """Download NSE masters, parse them, write cache, and return cache data."""
    equity_csv = _fetch_url(EQUITY_MASTER_URL)
    name_change_csv = _fetch_url(NAME_CHANGE_URL)
    symbol_change_csv = _fetch_url(SYMBOL_CHANGE_URL)

    records = _parse_equity_master(equity_csv)
    name_aliases = _parse_name_changes(name_change_csv)
    symbol_changes = _parse_symbol_changes(symbol_change_csv)
    records = _apply_aliases(records, name_aliases, symbol_changes)

    data = {
        "schema_version": 1,
        "source": "NSE",
        "source_urls": {
            "equity_master": EQUITY_MASTER_URL,
            "name_change": NAME_CHANGE_URL,
            "symbol_change": SYMBOL_CHANGE_URL,
        },
        "generated_at": int(time.time()),
        "records": records,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    return data


def _read_cache(cache_path: Path = CACHE_PATH) -> dict[str, Any] | None:
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_symbol_master(
    cache_path: Path = CACHE_PATH,
    ttl_seconds: int = CACHE_TTL_SECONDS,
    refresh: bool = True,
) -> dict[str, Any] | None:
    """Load fresh cache; if refresh fails, use stale cache when present."""
    cached = _read_cache(cache_path)
    generated_at = int(cached.get("generated_at", 0)) if isinstance(cached, dict) else 0
    if cached and time.time() - generated_at <= ttl_seconds:
        return cached

    if refresh:
        try:
            return refresh_symbol_master(cache_path)
        except Exception:
            if cached:
                return cached
            return None

    return cached


def _iter_record_names(record: dict[str, Any]) -> list[str]:
    names = [str(record.get("name", ""))]
    names.extend(str(alias) for alias in record.get("aliases", []) if alias)
    return names


def _build_indexes(data: dict[str, Any]) -> dict[str, Any]:
    symbol_index: dict[str, dict[str, Any]] = {}
    name_index: dict[str, dict[str, Any]] = {}
    stripped_index: dict[str, dict[str, Any]] = {}

    for record in data.get("records", []):
        symbol = str(record.get("symbol", "")).strip().upper()
        if not symbol:
            continue
        symbol_index[normalize_key(symbol)] = record
        for previous in record.get("previous_symbols", []):
            symbol_index[normalize_key(str(previous))] = record
        for name in _iter_record_names(record):
            name_key = normalize_key(name)
            stripped_key = stripped_name_key(name)
            if name_key:
                name_index.setdefault(name_key, record)
            if stripped_key:
                stripped_index.setdefault(stripped_key, record)

    return {
        "symbol": symbol_index,
        "name": name_index,
        "stripped": stripped_index,
    }


def _resolve_record(record: dict[str, Any], source: str) -> dict[str, str]:
    return _ticker_result(str(record.get("symbol", "")).strip().upper(), str(record.get("name", "")).strip(), source)


def resolve_from_symbol_master(
    text: str,
    cache_path: Path = CACHE_PATH,
    refresh: bool = True,
) -> dict[str, str]:
    """Resolve text against cached official NSE symbol data."""
    query = str(text or "").strip()
    normalized = normalize_key(query)
    if not normalized:
        return _empty_result()

    data = load_symbol_master(cache_path=cache_path, refresh=refresh)
    if not data:
        return _empty_result()

    indexes = _build_indexes(data)

    record = indexes["symbol"].get(normalized)
    if record:
        return _resolve_record(record, "symbol_master_symbol")

    record = indexes["name"].get(normalized)
    if record:
        return _resolve_record(record, "symbol_master_name")

    stripped = stripped_name_key(query)
    record = indexes["symbol"].get(stripped) or indexes["stripped"].get(stripped)
    if record:
        return _resolve_record(record, "symbol_master_stripped")

    if len(stripped) < 5:
        return _empty_result()

    candidates = list(indexes["stripped"].keys())
    matches = difflib.get_close_matches(stripped, candidates, n=2, cutoff=0.90)
    if not matches:
        return _empty_result()

    best = matches[0]
    score = difflib.SequenceMatcher(None, stripped, best).ratio()
    if score < 0.90:
        return _empty_result()
    if len(matches) > 1:
        second_score = difflib.SequenceMatcher(None, stripped, matches[1]).ratio()
        if score - second_score < 0.03:
            return _empty_result()

    return _resolve_record(indexes["stripped"][best], "symbol_master_fuzzy")
