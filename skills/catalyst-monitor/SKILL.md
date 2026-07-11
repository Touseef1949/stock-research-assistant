---
name: catalyst-monitor
description: Build a sourced catalyst and monitoring view from recent news, reported results, company documents, and dated event evidence.
when_to_use: Use for upcoming catalysts, event calendars, what-to-watch questions, and ongoing thesis monitoring.
command: /catalysts
required_tools:
  - get_recent_news
  - get_filing_results
  - get_earnings_transcript
  - get_analyst_consensus
supporting_skills:
  - earnings-deep-dive
  - risk-governance
---

# Catalyst Monitor

1. Verify the security and as-of time for every event or news item.
2. Separate confirmed dated events from inferred monitoring windows.
3. Link each catalyst to the operating metric, expectation, or thesis component it can change.
4. Include positive and negative catalysts; do not treat news volume as sentiment quality.
5. State the expected read-through, evidence source, monitoring trigger, and confidence.
6. Do not invent earnings dates, regulatory decisions, or management events when a primary source is absent.

## Output

- Confirmed recent developments
- Upcoming or inferred catalyst windows
- Bullish and bearish read-throughs
- Metrics and documents to monitor
- Thesis prove/kill triggers
- Missing dates or evidence requiring verification
