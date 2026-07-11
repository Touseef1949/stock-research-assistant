---
name: peer-valuation
description: Compare a stock with relevant listed peers using consistent periods, definitions, growth, quality, and valuation multiples.
when_to_use: Use for peer comparisons, relative valuation, or questions about whether a stock is cheap or expensive.
command: /peers
required_tools:
  - get_market_snapshot
  - get_fundamental_metrics
  - get_valuation_inputs
  - get_peer_metrics
---

# Peer Valuation

1. Define a defensible peer set based on business model, geography, scale, and economics.
2. Align metric periods and definitions before comparing multiples.
3. Calculate peer median, quartiles, subject premium/discount, and outliers with the bundled deterministic tools.
4. Explain whether a premium or discount is supported by growth, margins, returns, leverage, or risk.
5. Do not call a stock cheap from one multiple alone.

## Output

- Peer-selection rationale
- Comparable metric table
- Premium/discount and outlier analysis
- Quality/growth justification
- Relative valuation conclusion and limitations
