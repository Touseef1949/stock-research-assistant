# Skill-Driven Research Architecture

## Purpose

The Stock Research Assistant separates decision workflows, deterministic data operations, and language-model synthesis:

- **Skills** are versioned `SKILL.md` research procedures.
- **Tools** retrieve data or perform deterministic calculations.
- **The orchestrator** routes the request, loads only the selected procedures, executes required tools, synthesizes an answer, and validates its citations.

The language model never owns market-data retrieval or financial calculations. When the model is unavailable or produces invalid citations, the system returns a deterministic evidence-backed report.

## Execution flow

```text
User decision/question
        │
        ▼
Deterministic router ── direct fact ──► one normalized tool ──► cited answer
        │
        └── workflow ──► load SKILL.md ──► required tools
                                                │
                                                ▼
                                      normalized evidence store
                                                │
                              ┌─────────────────┴─────────────────┐
                              ▼                                   ▼
                     grounded LLM synthesis             deterministic fallback
                              └─────────────────┬─────────────────┘
                                                ▼
                                      evidence-citation validator
                                                ▼
                           report + sources + confidence + audit trace
```

## Runtime components

| Component | Responsibility |
|---|---|
| `core/skills.py` | Discovers skills, exposes compact catalog entries, and loads full procedures/bundled tools lazily. |
| `core/research_router.py` | Routes simple facts directly and multi-step decisions to the narrowest workflow. |
| `core/research_contracts.py` | Defines evidence, tool-result, route, trace, workflow, and response envelopes. |
| `research_tools/` | Normalized deterministic market and external research adapters. |
| `services/research_workflow.py` | Loads procedures, executes required tools, and assembles evidence and trace events. |
| `services/research_orchestrator.py` | Produces direct, agent, or fallback answers from the selected workflow. |
| `core/research_validation.py` | Rejects unknown citations and flags unsourced numerical answers. |
| `services/document_client.py` | Downloads approved transcript documents with redirect, byte, page, and content limits. |
| `eval/run_research_evals.py` | Release gate for routing accuracy and answer grounding. |

## Shipped workflows

| Command | Skill | Main result |
|---|---|---|
| `/snapshot` | `stock-snapshot` | Market, quality, valuation, technical, and risk overview |
| `/fundamentals` | `fundamental-quality` | Growth, profitability, capital efficiency, leverage, and quality |
| `/entry` | `technical-entry` | Trend, momentum, levels, volatility, and invalidation conditions |
| `/peers` | `peer-valuation` | Target-versus-peer metrics and premium/discount evidence |
| `/valuation` | `valuation-scenarios` | Transparent valuation inputs and scenario workflow |
| `/risks` | `risk-governance` | Financial, market, governance, and evidence-quality risks |
| `/earnings` | `earnings-deep-dive` | Results, transcript, guidance, and thesis implications |
| `/catalysts` | `catalyst-monitor` | Recent developments, event windows, read-throughs, and monitoring triggers |
| `/thesis` | `investment-thesis` | Variant perception, bull/bear cases, catalysts, risks, and falsifiers |

## Source and confidence policy

Source precedence is:

1. Exchange-hosted or company-reported documents
2. Structured Screener financial tables and public document index
3. Zerodha Kite live prices where locally authorized
4. Yahoo Finance structured market data
5. Explicitly labelled public-web fallback

Every tool response records source, as-of time, confidence, fallback status, warnings, and evidence IDs. Synthetic/insufficient price history forces low-confidence technical output. A weaker fallback never silently replaces a stronger source.

## Transcript safety

Transcript retrieval is restricted to HTTPS URLs in the Screener/NSE/BSE source chain. Redirects are checked before following. Downloads are streamed and limited to 8 MB, extraction is limited to 25 pages, and oversized page content streams are skipped. Retrieved text is explicitly treated as untrusted evidence, not instructions.

## Adding a skill

1. Create `skills/<slug>/SKILL.md` with `name`, `description`, `when_to_use`, `command`, and `required_tools` frontmatter.
2. Write a procedure that defines evidence requirements, calculation rules, output structure, limitations, and falsifiers.
3. Add router cases in `eval/workflow_cases.yaml`.
4. Add optional deterministic calculations in `skills/<slug>/tools.py`.
5. Run `python eval/run_research_evals.py` and the full test suite.

## Adding a tool

1. Return `ToolResult`; never return provider-specific data directly to the UI.
2. Create evidence records for decision-relevant values.
3. Preserve source URLs, timestamps, units, periods, confidence, and warnings.
4. Bound network time, response size, and retries.
5. Add mocked success, failure, fallback, and safety tests.
6. Register the callable in `research_tools.TOOL_FUNCTIONS`.

## Release gates

```bash
python eval/run_research_evals.py
python -m pytest tests/ -x --tb=short
python -m pytest tests/ --cov=. --cov-report=term-missing
```

The routing evaluation must remain at or above 90%. All grounding cases must pass, every declared shipped tool must be registered, and the ordinary test/coverage/security gates remain mandatory.
