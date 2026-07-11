---
name: technical-entry
description: Evaluate trend, momentum, volatility, drawdown, support/resistance, and evidence-based entry conditions.
when_to_use: Use for chart, entry timing, momentum, RSI, support/resistance, or technical-risk questions.
command: /entry
required_tools:
  - get_market_snapshot
  - get_technical_metrics
  - evaluate_risk_flags
---

# Technical Entry Review

1. Require adequate real price history before interpreting indicators.
2. Check trend alignment across price, EMA20, and EMA50.
3. Evaluate RSI and MACD as supporting signals, never as standalone decisions.
4. State support, resistance, volatility, and maximum drawdown.
5. Express entry conditions as scenarios with invalidation levels, not guaranteed forecasts.

## Output

- Current setup and data quality
- Trend and momentum
- Important price levels
- Base, breakout, and pullback scenarios
- Invalidation and downside risks
