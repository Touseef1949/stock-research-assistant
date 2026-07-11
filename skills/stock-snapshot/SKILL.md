---
name: stock-snapshot
description: Produce a concise, evidence-backed company and market snapshot with valuation, quality, momentum, and risk indicators.
when_to_use: Use for broad stock overviews, health checks, quick reports, and requests that do not require a narrower specialist workflow.
command: /snapshot
required_tools:
  - get_market_snapshot
  - get_fundamental_metrics
  - get_technical_metrics
  - evaluate_risk_flags
---

# Stock Snapshot

1. Resolve and verify the exchange-listed security before analysis.
2. Load the current market snapshot and record its source and as-of time.
3. Load fundamental and technical metrics through deterministic tools.
4. Run the risk gate. Do not make a strong technical claim when price history is insufficient or synthetic.
5. Separate reported facts, calculated metrics, and interpretation.

## Output

- Snapshot: company, symbol, price, market capitalization, and source freshness.
- Quality and valuation: key multiples, profitability, growth, and leverage.
- Price action: trend, momentum, support/resistance, volatility, and drawdown.
- Risks and evidence gaps.
- What the investor should research next.

This is research workflow support, not personalized investment advice.
