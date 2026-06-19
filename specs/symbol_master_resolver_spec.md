# Symbol Master Resolver Spec

## Why we are changing this

The current resolver works for many popular tickers but still misses valid Indian stocks when the user provides:
- full company legal names (e.g. `EIEL Limited`)
- slight name variants
- smallcap / recent-listing names where Yahoo search is inconsistent

Verified examples on 2026-06-19:
- `EIEL` -> resolves
- `EIEL Limited` -> fails (`yf.Search` returns 0 results)
- `Baluforge` -> currently resolves via search/direct path
- `Balu Forge` -> resolves

This proves the current resolver is not fundamentally wrong, but it is too dependent on Yahoo search behavior and too weak on company-name normalization.

## Current functionality vs proposed functionality

### Current functionality
1. Normalize input by uppercasing and removing punctuation.
2. Check `SPECIAL_TICKERS` table.
3. Check `KNOWN_TICKERS` hardcoded alias map.
4. Try direct `{normalized}.NS` validation via yfinance history.
5. Fallback to `yf.Search(...)` and convert BSE `.BO` to `.NS` where reasonable.
6. If still unresolved, return `unknown`.

### Current weaknesses
1. Hardcoded alias map does not scale to all NSE stocks.
2. Legal suffixes like `LIMITED` / `LTD` cause misses.
3. Company-name resolution depends too much on Yahoo search quality.
4. Recent/smallcap Indian equities are brittle.
5. Every newly discovered miss currently requires code patching.

### Proposed functionality
Add a local, cached NSE symbol master service and use it as the PRIMARY resolution path.

New resolution order:
1. Normalize input
2. Check `SPECIAL_TICKERS`
3. Check `KNOWN_TICKERS`
4. Check local symbol master exact symbol match
5. Check local symbol master exact normalized company-name match
6. Check local symbol master exact stripped-name match (remove legal suffixes like LTD/LIMITED/INDUSTRIES/ENGINEERS/COMPANY/CORPORATION)
7. Check local symbol master fuzzy match (RapidFuzz, thresholded)
8. Only then use yfinance search as tertiary fallback
9. Return `unknown` if still unresolved

## Data source for symbol master
Use official NSE downloadable security list as the primary master source.

Source discovered live on 2026-06-19:
- https://www.nseindia.com/static/market-data/securities-available-for-trading

Expected implementation approach:
- Add a small service module that downloads/parses the NSE equities CSV (not ETFs / SME unless clearly separated and intentionally included)
- Cache the parsed master locally to a JSON file inside the project (NOT Downloads)
- Reuse cached file unless stale
- Refresh on demand or when cache is older than a TTL (e.g. 24h)

## Files to add / modify

### New files
1. `services/symbol_master.py`
   - load local cached master
   - refresh master from NSE source
   - normalize company names
   - perform exact + stripped + fuzzy matching
   - expose a function like `resolve_from_symbol_master(text) -> dict[str, str]`

2. `data/symbol_master_nse.json` (generated cache; create if needed)
   - cached normalized symbol records

### Existing files to modify
1. `logic.py`
   - integrate symbol-master resolution into `resolve_ticker()`
   - keep existing `SPECIAL_TICKERS` and `KNOWN_TICKERS`
   - use symbol master before yfinance search
   - preserve output shape `{symbol, name, source}`

2. `tests/test_logic.py`
   - add tests for symbol-master resolution precedence and matching

3. `tests/test_services_coverage_gaps.py` or new focused test file
   - test symbol master parsing / caching / normalization helpers

## Normalization rules
The symbol master service should support at least these normalization helpers:
- uppercase
- remove punctuation/spaces for canonical matching
- legal suffix stripping tokens such as:
  - LIMITED
  - LTD
  - LIMITED.
  - INDUSTRIES
  - INDUSTRY
  - ENGINEERS
  - ENGINEERING
  - COMPANY
  - CO
  - CORPORATION
  - CORP
  - INDIA (optional only for secondary stripped key, not primary)

Important: do NOT over-strip in the primary key. Keep two forms:
1. strict normalized name
2. stripped-name normalized key for fallback matching

## Matching behavior
### Exact symbol match
- `EIEL` -> `EIEL.NS`
- `BALUFORGE` -> `BALUFORGE.NS`

### Exact company-name match
- `Enviro Infra Engineers Limited` -> `EIEL.NS`
- `Balu Forge Industries Limited` -> `BALUFORGE.NS`

### Stripped-name match
- `EIEL Limited` should still hit the symbol `EIEL` if symbol or alias key exists
- `Balu Forge` should match `Balu Forge Industries Limited`

### Fuzzy match
Use a conservative threshold so we do not hallucinate wrong tickers.
Suggested:
- exact symbol/name matches first
- fuzzy only if score >= 90 for stripped-name keys
- return top single confident match only
- otherwise return unresolved rather than guessing

## Source labeling
Use clear `source` values, e.g.:
- `special`
- `map`
- `symbol_master_symbol`
- `symbol_master_name`
- `symbol_master_stripped`
- `symbol_master_fuzzy`
- `direct`
- `search`
- `unknown`

## Constraints
- Do NOT use Kite as the public stock master source
- Do NOT store cache under `~/Downloads`
- Keep existing yfinance fallback behavior as tertiary fallback
- Avoid network fetch on every request; use local cache + TTL
- If NSE fetch fails and cache exists, use stale cache rather than failing
- If no cache exists and fetch fails, fall back to existing resolver path gracefully

## Tests to include
1. `EIEL` resolves
2. `EIEL Limited` resolves to `EIEL.NS`
3. `Enviro Infra Engineers Limited` resolves to `EIEL.NS`
4. `Baluforge` resolves to `BALUFORGE.NS`
5. `Balu Forge` resolves to `BALUFORGE.NS`
6. `Balu Forge Industries Limited` resolves to `BALUFORGE.NS`
7. Fuzzy threshold does not turn garbage into fake tickers
8. If symbol master fetch fails but cache exists, cached data is used
9. If symbol master unavailable, resolver still falls back to old search logic

## Deliverable
A working resolver architecture that no longer requires us to hardcode every Indian stock alias one by one.
