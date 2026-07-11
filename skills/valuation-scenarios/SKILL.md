---
name: valuation-scenarios
description: Build transparent bear, base, and bull valuation cases from explicit assumptions and deterministic calculations.
when_to_use: Use for fair-value, target-price, DCF, reverse-valuation, or valuation-sensitivity questions.
command: /valuation
required_tools:
  - get_market_snapshot
  - get_fundamental_metrics
  - get_valuation_inputs
  - get_analyst_consensus
---

# Valuation Scenarios

1. Identify the valuation method appropriate for the available evidence.
2. State every key assumption, unit, period, and source.
3. Build bear, base, and bull cases; never present one point estimate as certain.
4. Use the bundled deterministic scenario tool for price/upside calculations.
5. Explain what operational result would justify each case.

## Output

- Current valuation and source timestamp
- Method and assumptions
- Bear/base/bull table
- Sensitivities and implied upside/downside
- Key dependencies and invalidation conditions
