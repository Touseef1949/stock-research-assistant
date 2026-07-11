---
name: risk-governance
description: Assess financial, market, governance, concentration, dilution, and evidence-quality risks without inventing missing facts.
when_to_use: Use for downside, governance, pledging, auditor, leverage, volatility, or red-flag questions.
command: /risks
required_tools:
  - get_fundamental_metrics
  - get_technical_metrics
  - evaluate_risk_flags
---

# Risk and Governance Review

1. Separate verified governance facts from missing or unverified information.
2. Review leverage, drawdown, volatility, and financial-quality warnings.
3. Review promoter pledging, auditor changes, related-party transactions, dilution, and regulatory issues only when sourced.
4. Rank risks by severity, likelihood, and thesis impact.
5. Define monitoring indicators and explicit thesis falsifiers.

## Output

- Highest-priority verified risks
- Market and balance-sheet risk
- Governance observations
- Unknowns requiring primary-source verification
- Monitoring and thesis-kill triggers
