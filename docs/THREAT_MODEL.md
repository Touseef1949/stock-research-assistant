# AI and financial-data threat model

## Protected assets

- research inputs, generated reports, history, account and payment state
- model, market-data, Supabase, Razorpay, and optional Kite credentials
- local broker/portfolio data and any non-public financial information
- prompts, skill procedures, evaluation cases, traces, logs, and release state

## Trust boundaries

Ticker queries, uploaded documents, web content, filings, and transcripts are
untrusted data. Deterministic market/research tools normalize evidence before
the model synthesizes it. Model output returns to the UI and exported reports.
Market-data providers, DeepSeek, Supabase, Razorpay, Hugging Face, and optional
local Kite access are separate external boundaries.

## Principal threats and controls

| Threat | Control |
| --- | --- |
| Prompt injection in web pages, documents, or issuer text | Treat sources as evidence, not instructions; bounded tools, versioned prompts, citation validation, and deterministic fallback. |
| Fabricated or stale financial claims | Source/confidence contracts, explicit warnings, freshness checks, research evals, and no silent synthetic prices. |
| Broker or portfolio data leakage | Kite stays local-only, secrets and private records are ignored, and no order-placement path is part of the public app. |
| Credential or payment-data exposure | Deployment secrets, push protection, Gitleaks, redacted logs, and no secrets in prompts or reports. |
| Misleading investment output | Educational-use language, evidence links, risk flags, limitations, and mandatory human judgement. |
| Cost or denial-of-wallet abuse | Auth/usage gates, bounded workflows, direct factual routing, and non-LLM health/load checks. |
| Dependency or CI compromise | Exact locks, Dependabot, read-only workflow tokens, and immutable action pins. |

## Privacy and trading boundary

Do not submit credentials, regulated personal data, unpublished company data,
or portfolio information that is not approved for the configured providers.
Kite integration is for approved personal/local data use only. The public app
must not expose broker details, live portfolios, or order placement.

## Residual risk

Sources can be wrong, delayed, or incomplete; models can misread or overstate
evidence. A passing evaluation does not make a security suitable for purchase.
Users must independently verify material claims and make their own decisions.
