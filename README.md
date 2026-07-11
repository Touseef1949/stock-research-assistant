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

# Stock Research Assistant — Production Runbook

> **Status**: Production-grade | Live at https://tshaik1990-stock-research-assistant.hf.space

## Architecture

```
Stock_Research_Assistant/
├── app.py                    # Streamlit composition layer (3,869 lines)
├── logic.py                  # Pure business logic (scoring, formatting)
├── payment.py                # Supabase auth + Razorpay payments
├── yf_client.py              # Yahoo Finance API client
├── ui.py                     # Reusable Streamlit UI components
├── core/
│   ├── models.py             # Existing report models
│   ├── skills.py             # Progressive SKILL.md registry
│   ├── research_router.py    # Direct-vs-workflow routing
│   ├── research_contracts.py # Evidence/tool/trace contracts
│   └── research_validation.py# Evidence citation gate
├── skills/                   # 9 decision-oriented research procedures
├── research_tools/           # Normalized deterministic research tools
├── services/
│   ├── market_data.py        # YF/Screener/web fallback pipeline (96% coverage)
│   ├── analysis_pipeline.py  # Agent pipeline + local fallback (90% coverage)
│   ├── research_workflow.py  # Skill loading and tool execution
│   ├── research_orchestrator.py # Grounded synthesis + fallback
│   ├── document_client.py    # Bounded transcript extraction
│   ├── report_history.py     # Report persistence + JSON serialization
│   └── error_logging.py      # Structured JSONL error logging
├── deep_research/            # Pro deep-research module (10 agents)
├── eval/                     # Routing and grounding release gates
├── docs/
│   └── SKILL_ARCHITECTURE.md # Extension and operations guide
├── tests/                    # Unit, integration, AppTest, and workflow eval tests
├── scripts/
│   └── health_monitor.py     # Uptime + error log health check
├── .github/workflows/
│   └── test.yml              # CI/CD: test gate + secrets scan
├── .gitignore                # Blocks secrets.toml, logs/, pycache
└── .gitleaks.toml            # Secrets detection rules
```

## Quick Reference

| Task | Command |
|------|---------|
| Run tests | `/usr/local/bin/python3 -m pytest tests/ -q` |
| Run research evals | `/usr/local/bin/python3 eval/run_research_evals.py` |
| Coverage report | `/usr/local/bin/python3 -m pytest tests/ --cov=. --cov-report=term-missing` |
| Deploy to HF Space | `git push hf main` (pre-push hook runs tests first) |
| Health check | `/usr/local/bin/python3 scripts/health_monitor.py` |
| View error log | `cat logs/errors.jsonl \| python3 -m json.tool` |
| Skip pre-push tests | `git push hf main --no-verify` (emergencies only) |

## Deploy Workflow

1. **Make changes** in `app.py`, `logic.py`, `services/`, etc.
2. **Run tests locally**: `pytest tests/ -q`
3. **Commit**: `git add . && git commit -m "feat: ..."`
4. **Push to HF Space**: `git push hf main`
   - Pre-push hook runs `pytest tests/ -q` automatically
   - If tests fail, push is blocked. Fix failures or `--no-verify` (emergency).
5. **Verify deploy**: Wait ~60 seconds, then check `https://tshaik1990-stock-research-assistant.hf.space`

## CI/CD (GitHub Actions)

When the repo is connected to GitHub:
- `.github/workflows/test.yml` runs on every push/PR
- Test gate: all tests must pass + coverage ≥ 90%
- Research gate: routing accuracy ≥90% and all grounding cases pass
- Security: gitleaks scans for exposed API keys/secrets

## Monitoring

**Health monitor** — runs every 4 hours (laptop-must-be-awake, cron job `41b047d120b5`):
- Checks HF Space `/health` endpoint → HTTP 200
- Checks error log for spike (>10 recent errors)
- Alerts via Telegram on failure

**Error logging** — `services/error_logging.py`:
- Writes structured JSONL to `logs/errors.jsonl`
- Captured at: main exception handler in `app.py`
- Auto-trimmed to 500 lines
- View: `cat logs/errors.jsonl | python3 -m json.tool`

## Secrets Management

- `.streamlit/secrets.toml` — **NEVER committed** (blocked by `.gitignore`)
- `.gitleaks.toml` — config for automated secrets scanning
- API keys loaded from `~/.hermes/.env` as fallback (for cron/local dev)

## Production Checklist

- [x] Pre-push test hook
- [x] CI/CD workflow (GitHub Actions)
- [x] Health monitoring (4-hour cron)
- [x] Structured error logging
- [x] Secrets audit — git history clean
- [x] `.gitignore` blocks secrets, logs, pycache
- [x] `.gitleaks.toml` for automated scanning
- [x] 95% code coverage (674 tests)
- [x] Service modules extracted (market_data, analysis_pipeline, report_history)
- [x] Mobile-responsive UI
- [x] Institutional PDF reports
- [x] Payment/auth layer (Razorpay + Supabase)
- [x] Live Kite integration — live LTP + OHLC via Zerodha Kite, graceful fallback to yfinance
- [x] Load testing — 10 concurrent users, 0 failures, median 230ms
- [x] GitHub remote — https://github.com/Touseef1949/stock-research-assistant
- [x] Progressive skill registry and lazy procedure loading
- [x] Direct factual routing that skips expensive agent synthesis
- [x] Evidence/source/confidence contracts and audit trace
- [x] Peer, filing/results, and bounded transcript tools
- [x] Citation validation with deterministic grounded fallback
- [x] Routing and grounding evaluation gate

See [Skill-Driven Research Architecture](docs/SKILL_ARCHITECTURE.md) for the execution contract and extension guide.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "All data sources unreachable" | HF Spaces shared IP rate-limited by YF/Screener | Wait 1-2 min, retry |
| Report shows "Local fallback" | DeepSeek API key missing or expired | Check `.streamlit/secrets.toml` |
| Deep Research tab blank for free users | Expected — Pro feature | User upgrades to Pro |
| Health monitor fails | HF Space cold start | Space auto-wakes on next request |
| OTP not sending | Supabase config missing | Check `payment.py` Supabase keys |
