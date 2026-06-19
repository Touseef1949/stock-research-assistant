# Ticker Resolver Fix Spec

## Problem
`resolve_ticker()` in `logic.py` fails to resolve many valid NSE stocks, producing
"We couldn't find a listed NSE ticker for '{symbol}'" errors.

## Root Cause (verified by live testing)

### Issue 1: yfinance Search returns BSE, not NSE
`yf.Search("Tata Steel")` returns `TATASTEEL.BO` (BSE exchange), NOT `TATASTEEL.NS`.
The `_search_yfinance()` function in `logic.py` only accepts results with:
- symbol ending in `.NS`, OR
- exchange in `{"NSE", "NSI"}`

So all BSE results are filtered out → returns empty.

### Issue 2: Direct ticker validation fails on rate-limit
`_validate_ticker()` calls `ticker_history(symbol, period="5d")` which hits yfinance API.
When rate-limited (429), `ticker_history` raises `YFinanceRateLimitError`, which
`_validate_ticker` catches as a generic Exception and returns `False`.
This kills the direct-ticker resolution path entirely.

### Combined effect
- Direct validation fails (rate limit) → `False`
- KNOWN_TICKERS map doesn't have the stock → no match
- yfinance search returns only BSE results → filtered out → empty
- Result: "couldn't find a listed NSE ticker"

## Required Fixes (all in `logic.py`)

### Fix 1: `_search_yfinance()` — accept BSE results and convert to NSE
When yfinance search returns a `.BO` result (BSE), convert it to `.NS` since
the vast majority of NSE/BSE stocks share the same ticker symbol.
e.g., `TATASTEEL.BO` → `TATASTEEL.NS`

Modified scoring logic:
- `.NS` suffix → score 3 (best)
- exchange NSE/NSI → score 2
- `.BO` suffix or exchange BSE → score 1 (convert to .NS)
- other → score 0 (skip)

Accept any result with score >= 1. For BSE results, strip `.BO` and append `.NS`.

### Fix 2: `_validate_ticker()` — don't swallow rate-limit errors
Currently catches ALL exceptions and returns `False`.
Change: if the exception is a `YFinanceRateLimitError` (from `yf_client`), 
re-raise it OR return `True` optimistically (the symbol might be valid,
just can't verify right now). 

Preferred approach: import `YFinanceRateLimitError` from `yf_client` and
return `True` on rate-limit (optimistic validation), return `False` only on
genuine "symbol not found" errors (empty DataFrame, KeyError, etc.).

### Fix 3: Expand `KNOWN_TICKERS` map
Add commonly searched NSE stocks that aren't in the current map. At minimum add:
- TATASTEEL / TATASTEELLTD
- HDFCLIFE / HDFCLIFELTD
- NALCO / NATIONALALUMINIUM / NATIONALUM
- SUPRIYA / SUPRIYALIFESCIENCE
- AVANTIFEED / AVANTIFEEDS
- EICHERMOT / EICHERMOTORS
- BAJAJFINSV / BAJAJFINANCEANDINSURANCE
- DIVISLAB / DIVISLABORATORIES
- PIDILITIND / PIDILITINDUSTRIES
- SIEMENS / SIEMENSINDIA
- DABUR / DABURINDIA
- GODREJCP / GODREJCONSUMER
- MARICO / MARICOLTD
- BERGERPAINT / BERGERPAINTS
- MUTHOOTFIN / MUTHOOTFINANCE
- CHOLAFIN / CHOLAFINANCE
- PFC / POWERFINANCE
- REC / RECLTD
- GAIL / GAILINDIA
- BPCL / BHARATPETROLEUM
- IOC / INDIANOIL
- VEDL / VEDANTA
- HINDALCO / HINDALCOINDUSTRIES
- JINDALSTEL / JINDALSTEELANDPOWER
- SAIL / STEELAUTHORITYOFINDIA
- UPL / UPLLTD
- PIIND / PIINDUSTRIES
- BANDHANBNK / BANDHANBANK
- FEDERALBNK / FEDERALBANK
- IDFCFIRSTB / IDFCFIRSTBANK
- RBLBANK / RBLBANKLTD
- INDUSINDBK / INDUSIND
- AMBUJACEM / AMBUJACEMENTS
- GRASIM / GRASIMINDUSTRIES
- SHREECEM / SHREECEMENT
- ACC / ACCLTD
- BAJAJHLDNG / BAJAJHOLDINGS
- M&M / MAHINDRA / MAHINDRAMAHINDRA (note: M&M normalizes to MM)
- EICHERMOT / EICHERMOTORS
- HEROMOTOCO / HEROMOTORS
- EICHERMOT / EICHERMOTORS
- BOSCHLTD / BOSCH
- MCDOWELL-N / MCDOWELLN / UNITEDSPIRITS (note: hyphen in ticker)
- CONCOR / CONTAINERCORPORATION
- NHPC / NHPCLTD
- SJVN / SJVNLTD
- IRCTC / IRCTCLTD
- INDHOTEL / INDIANHOTELS
- FORTIS / FORTISHEALTHCARE
- APOLLOHOSP / APOLLOHOSPITALS
- MAXHEALTH / MAXHEALTHCARE
- LALPATHLAB / DRLALPATHLABS
- METROPOLIS / METROPOLISHEALTHCARE

### Fix 4: Handle M&M and hyphenated tickers
`_normalize_query` strips all non-alphanumeric chars. `M&M` becomes `MM` which is wrong.
The NSE ticker is `M&M.NS`. Need special handling:
- After normalization, check for known special cases like `MM` → `M&M.NS`
- For hyphenated tickers like `MCDOWELL-N`, normalize to `MCDOWELLN` but map to `MCDOWELL-N.NS`

Add a `SPECIAL_TICKERS` dict for these cases, checked before the regex validation.

### Fix 5: Add fallback NSE direct-validation
If yfinance search returns nothing useful, try the direct `{normalized}.NS` symbol
WITHOUT validation (skip `_validate_ticker`) as a last resort. The downstream
`load_market_data` will fail gracefully if the symbol is truly invalid.

## Files to Modify
- `logic.py` — all fixes above
- `tests/test_logic.py` (or `tests/test_resolver.py`) — add tests for:
  - BSE→NSE conversion in search
  - Rate-limit optimistic validation
  - New KNOWN_TICKERS entries
  - Special tickers (M&M, MCDOWELL-N)

## Constraints
- Do NOT modify `yf_client.py` — the retry/backoff logic there is correct
- Do NOT change the `resolve_ticker()` function signature
- Do NOT break existing tests
- Keep the `_normalize_query` function as-is (just add special-case handling after it)
- The `_ticker_result` helper must still work the same way
