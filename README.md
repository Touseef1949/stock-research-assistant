---
title: Stock Research Assistant
emoji: 📊
colorFrom: green
colorTo: blue
sdk: docker
app_file: app.py
pinned: false
license: mit
---

# Stock Research Assistant

[Live app](https://tshaik1990-stock-research-assistant.hf.space) ·
[Case study](https://touseefshaik.com/apps/stock-research-assistant.html) ·
[Security policy](SECURITY.md) ·
[Changelog](CHANGELOG.md)

**Maturity:** public flagship, production-oriented, version 0.1.0.

Stock Research Assistant helps self-directed investors examine an NSE/BSE
company through multiple evidence-aware lenses: market context, fundamentals,
technical context, peers, governance, valuation, catalysts, risks, and a
structured thesis. It produces educational research, not investment advice,
and never places orders.

## Product flow

1. Enter a supported NSE/BSE symbol.
2. Choose a direct fact, standard analysis, or deeper research workflow.
3. Inspect evidence links, source/confidence labels, warnings, and the trace.
4. Export a report and independently verify material claims before deciding.

The [public case study](https://touseefshaik.com/apps/stock-research-assistant.html)
is the visual walkthrough.

## Architecture

```text
Streamlit UI -> research router -> direct factual path OR skill workflow
             -> normalized market/document/web tools
             -> evidence contracts + citation validation
             -> grounded model synthesis OR deterministic fallback
             -> UI and PDF report
```

`core/` contains contracts, routing, validation, and the progressive skill
registry. `research_tools/` normalizes evidence; `services/` orchestrates the
workflow; `skills/` holds decision procedures; `eval/` is the deterministic
routing/grounding release gate. See [RUNBOOK.md](RUNBOOK.md) and
[docs/SKILL_ARCHITECTURE.md](docs/SKILL_ARCHITECTURE.md).

## Supported environment

- Python 3.11 (the Docker, CI, and supported local runtime).
- A local virtual environment and internet access for dependency installation.
- Provider keys for model-backed analysis; deterministic fallbacks remain
  explicit when provider access is unavailable.
- Optional Supabase/Razorpay configuration for auth/payment features.

## Reproducible quick start

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
streamlit run app.py
```

`requirements.in` declares compatible runtime dependencies. Exact runtime and
development environments are in `requirements.lock` and
`requirements-dev.lock`. `requirements.txt` mirrors the runtime lock because
native Hugging Face Spaces mounts that file independently during its build.
Regenerate with:

```bash
uv pip compile requirements.in -o requirements.lock --python-version 3.11
uv pip compile requirements-dev.in -o requirements-dev.lock --python-version 3.11
cp requirements.lock requirements.txt
```

## Development quality gate

```bash
python -m pip install -r requirements-dev.lock
./scripts/quality.sh
```

This runs Ruff formatting/linting across core research boundaries, targeted
mypy checks, compilation, deterministic tests with at least 90% coverage, and
the research routing/grounding gate. CI executes the same command. Tests mock
network/model paths; paid model judgement is not a pull-request requirement.

The health/load paths never place orders or invoke model research:

```bash
python scripts/health_monitor.py
locust -f tests/load/locustfile.py \
  --host=https://tshaik1990-stock-research-assistant.hf.space
```

## Versioned AI behavior and evaluation

- Model: `deepseek-v4-flash` (`TEXT_MODEL_ID` in `core/ai_policy.py`).
- Prompt policies: `sra-analysis-v1`, `sra-research-orchestrator-v1`, and
  `sra-thesis-v1` in `core/ai_policy.py`.
- Golden routing/grounding cases: `eval/workflow_cases.yaml`.

The deterministic gate measures routing accuracy and evidence grounding.
Correctness, safety, latency, and cost remain separate release considerations;
one passing metric must not hide a regression in another.

## Data, privacy, and trading boundaries

- Public research uses approved market/web/document sources with explicit
  warnings when evidence is missing or stale.
- Kite is local-only for approved personal price data and is not a public SaaS
  data source. Broker credentials and portfolios must never be committed.
- The app has no order-placement path. Research output is educational and
  requires independent verification.
- Generated reports/history and authentication/payment records are private
  operational data, not repository artifacts.

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for controls and residual risk.

## Known limitations

- Market providers can be delayed, rate-limited, inconsistent, or unavailable.
- Web/issuer documents can change structure or contain adversarial text.
- Models can omit evidence, misinterpret a source, or overstate confidence.
- HF Spaces can cold-start; a health response does not prove research quality.
- Scanned PDFs without embedded text require OCR, which is not run on the basic
  hosted environment.

## Release and deployment

Pull requests must pass `quality` and `security`. Stable milestones use Semantic
Versioning and [CHANGELOG.md](CHANGELOG.md). The tagged GitHub revision is then
synchronized to the Hugging Face Space and verified through `/_stcore/health`
and a public, non-transactional research journey.

Contributions are described in [CONTRIBUTING.md](CONTRIBUTING.md). This project
is licensed under the [MIT License](LICENSE).
