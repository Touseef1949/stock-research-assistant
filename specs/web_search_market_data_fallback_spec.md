# Web Search Market Data Fallback Spec

## Goal
Add a tertiary web-search/web-scrape data layer so Stock Research Assistant can still generate a report when both Yahoo Finance and Screener.in are blocked from Hugging Face Spaces shared IPs.

## Current functionality

| Layer | Source | Current behavior |
|---|---|---|
| Primary | Yahoo Finance via yfinance | Full price/history/fundamentals. Can be rate-limited on HF shared IPs. |
| Secondary | Screener.in | Used only after Yahoo rate-limit. Can be blocked by Cloudflare from HF shared IPs. |
| Thin last resort | `_current_price_from_web_search()` | Only used if Screener succeeds but lacks price. Not used when Screener itself fails. |
| UI error | `is_rate_limit_error()` branch | Shows Yahoo-only rate-limit message, even when Screener/web also failed. |

## Proposed functionality

| Layer | Source | Proposed behavior |
|---|---|---|
| Primary | Yahoo Finance | unchanged |
| Secondary | Screener.in | unchanged for successful Screener responses |
| Tertiary | Web price fallback | If Screener fails, attempt web-derived current price using multiple public sources/snippets, then build minimal market_data with synthetic history and neutral technicals. |
| UI error | honest message | If all layers fail, say Yahoo + Screener + web fallback are unreachable, not just Yahoo rate-limit. |

## Implementation details

- Add `_market_data_from_web_search(nse_symbol, reason="")` in `app.py`.
- Add `_build_minimal_market_data(...)` helper so Screener fallback and web fallback can share a safe synthetic market-data shape.
- Extend `_current_price_from_web_search()` into a more resilient function that tries:
  1. Google Finance HTML (`https://www.google.com/finance/quote/{SYMBOL}:NSE`)
  2. NSE India quote API with a primed session
  3. existing DDGS snippet extraction
- Change `_market_data_from_screener()` so when `fetch_screener_financials()` returns `success=False`, it tries `_market_data_from_web_search()` before raising.
- Change the all-sources-failed RuntimeError text to avoid the phrase `rate-limiting`, so `is_rate_limit_error()` does not misclassify it as Yahoo-only.
- Add source badge for `web_search_fallback`.

## Tests

- `load_market_data()` returns `web_search_fallback` when Yahoo raises `YFinanceRateLimitError`, Screener fails, and web fallback returns a price.
- `_market_data_from_web_search()` builds valid market data with required keys.
- `_market_data_from_screener()` falls through to web fallback when Screener returns `success=False`.
- All-sources-failed error message is honest and does not trigger `is_rate_limit_error()`.

## Constraints

- No paid APIs.
- Preserve current Yahoo and Screener behavior when they work.
- Avoid adding new dependencies.
- Do not touch auth/payment logic in this change.
