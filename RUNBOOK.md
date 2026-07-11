# Stock Research Assistant — Operations Runbook

> **Live URL**: https://tshaik1990-stock-research-assistant.hf.space
> **Source**: https://github.com/Touseef1949/stock-research-assistant
> **HF Spaces remote**: `hf` (push to deploy)
> **Last updated**: 2026-07-11

---

## 1. Architecture Overview

```
Stock_Research_Assistant/
├── app.py                    # Streamlit composition layer (3,900+ lines)
├── logic.py                  # Pure business logic (scoring, formatting) — 0 st.* imports
├── payment.py                # Supabase auth + Razorpay payments
├── yf_client.py              # Yahoo Finance API client
├── ui.py                     # Reusable Streamlit UI components
├── core/                     # Report models, skill registry, router, contracts, validation
├── skills/                   # 9 progressively loaded research procedures
├── research_tools/           # Deterministic market/external tool facade
├── services/
│   ├── market_data.py        # YF/Screener/web fallback pipeline
│   ├── analysis_pipeline.py  # Agent pipeline + local fallback
│   ├── research_workflow.py  # Skill loading + normalized tool execution
│   ├── research_orchestrator.py # Direct/agent/fallback synthesis
│   ├── document_client.py    # Bounded approved-source transcript reader
│   ├── report_history.py     # Report persistence + JSON serialization
│   ├── kite_client.py        # Zerodha Kite live prices (local only)
│   ├── error_logging.py      # Structured JSONL error logging
│   └── __init__.py
├── deep_research/            # Pro deep-research module (10 agents)
│   ├── thesis_agent.py
│   ├── valuation.py
│   ├── peer_analysis.py
│   ├── governance.py
│   ├── risk_flags.py
│   ├── financial_trends.py
│   ├── analyst_targets.py
│   ├── screener_client.py
│   ├── report.py
│   └── __init__.py
├── eval/                     # Routing + evidence-grounding release gate
├── docs/SKILL_ARCHITECTURE.md
├── tests/                    # Unit + integration + AppTest + architecture tests
│   ├── load/
│   │   └── locustfile.py     # Locust load testing
│   └── *.py                  # Unit + integration + AppTest
├── scripts/
│   └── health_monitor.py     # Uptime + error log health check
├── .github/workflows/
│   └── test.yml              # CI: test gate (≥90% cov) + gitleaks
├── .streamlit/
│   ├── config.toml           # Theme, server, browser config
│   └── secrets.toml.example  # Template for secrets (real secrets.toml is gitignored)
├── .gitignore                # Blocks secrets.toml, logs/, pycache
├── .gitleaks.toml            # Secrets detection rules
├── Dockerfile                # Container deploy for HF Spaces
├── requirements.txt
└── README.md
```

## 2. Quick Reference

| Task | Command |
|------|---------|
| Run all tests | `/usr/local/bin/python3 -m pytest tests/ -q` |
| Run research release gate | `/usr/local/bin/python3 eval/run_research_evals.py` |
| Run tests (excl slow) | `/usr/local/bin/python3 -m pytest tests/ -q -k "not slow"` |
| Coverage report | `/usr/local/bin/python3 -m pytest tests/ --cov=. --cov-report=term-missing` |
| Deploy to HF Space | `git push hf main` (pre-push hook runs tests first) |
| Health check | `/usr/local/bin/python3 scripts/health_monitor.py` |
| View error log | `cat logs/errors.jsonl \| python3 -m json.tool` |
| Run locally | `streamlit run app.py` |
| Load test | `locust -f tests/load/locustfile.py --host https://tshaik1990-stock-research-assistant.hf.space` |

## 3. Deployment Pipeline

```
Local dev → git push origin main (GitHub)
                  ↓
         GitHub Actions CI
         ├── pytest (≥90% coverage gate)
         └── gitleaks (secrets scan)
                  ↓
         git push hf main (HF Spaces)
                  ↓
         HF Spaces Docker build → Live app
```

### Pre-push hook
The `.git/hooks/pre-push` hook runs the fast test suite before any push.
If tests fail, the push is blocked.

### HF Spaces cold start
HF Spaces sleeps after inactivity. First request after sleep takes ~10-15s
to spin up the Docker container. Subsequent requests are fast.

## 4. Secrets Configuration

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and fill in:

| Secret | Purpose | Where to get |
|--------|---------|-------------|
| `DEEPSEEK_API_KEY` | LLM for 5-agent pipeline | platform.deepseek.com |
| `SUPABASE_URL` | Auth backend | Supabase Dashboard → Settings → API |
| `SUPABASE_KEY` | Anon public key | Supabase Dashboard → Settings → API |
| `SUPABASE_SERVICE_KEY` | Service role (admin) | Supabase Dashboard → Settings → API |
| `RAZORPAY_KEY_ID` | Payment gateway | Razorpay Dashboard → Settings → API Keys |
| `RAZORPAY_KEY_SECRET` | Payment gateway secret | Razorpay Dashboard → Settings → API Keys |

**On HF Spaces**: Set these as Space Secrets in the HF Spaces settings page,
NOT in a committed secrets.toml file.

## 5. Monitoring & Alerting

### Health Monitor (`scripts/health_monitor.py`)
- Checks if the HF Space is responding
- Scans `logs/errors.jsonl` for recent errors
- Should be run via cron every 4 hours

### Error Logging (`services/error_logging.py`)
- All errors logged to `logs/errors.jsonl` as structured JSON
- Each entry: timestamp, module, error type, message, stack trace
- Review weekly for patterns

### CI/CD Monitoring
- GitHub Actions runs on every push to `main` and every PR
- Coverage gate: ≥90% or build fails
- Research routing gate: ≥90% accuracy
- Evidence grounding gate: every release case must pass
- Gitleaks: scans for leaked secrets in every push

## 6. Incident Response

### App is down (HF Space not responding)
1. Check HF Spaces status: https://huggingface.co/spaces/tshaik1990/stock-research-assistant
2. If Space is sleeping, any HTTP request will wake it (10-15s cold start)
3. If Space is in error state:
   - Check HF Spaces logs for build/runtime errors
   - Common causes: missing secrets, dependency version conflict, OOM
   - Fix locally → push to `hf` remote → Space rebuilds

### Tests failing in CI
1. Check GitHub Actions tab for failure details
2. Pull latest: `git pull origin main`
3. Reproduce locally: `/usr/local/bin/python3 -m pytest tests/ -q --tb=short`
4. Fix → commit → push (pre-push hook will verify)

### Coverage below 90%
1. Run: `/usr/local/bin/python3 -m pytest tests/ --cov=. --cov-report=term-missing`
2. Find uncovered lines (shown in report)
3. Add tests for those paths
4. Commit and push

### Payment (Razorpay) not working
1. Verify Razorpay keys in HF Spaces secrets
2. Check Razorpay dashboard for failed transactions
3. Test webhook endpoint if configured
4. Common: key rotation — update secrets on HF Spaces

### Auth (Supabase) not working
1. Verify Supabase URL and keys in HF Spaces secrets
2. Check Supabase dashboard → Authentication → Users
3. Verify email OTP is enabled in Supabase Auth settings
4. Check Supabase logs for errors

## 7. Known Limitations

- **yfinance rate limiting**: Yahoo Finance may rate-limit under heavy use.
  The app has a web-search fallback in `services/market_data.py`.
- **Kite data is local-only**: Kite Connect terms (§2a) prohibit SaaS use.
  Kite is only for personal/local price data; the SaaS uses yfinance (.NS).
- **HF Spaces cold start**: First request after sleep takes ~10-15s.
- **Upstream HTML changes**: Screener tables and document indexes are defensive parsers. Missing sections return explicit warnings rather than fabricated values.
- **Scanned transcripts**: PDFs without embedded text are reported as requiring OCR; OCR is not run on the CPU-basic Space.
- **app.py size**: 3,900+ lines. Should be split into `ui_sections/` modules
  in a future refactor. Not a production risk, but a maintainability concern.

## 8. Test Strategy

| Level | Count | Purpose |
|-------|-------|---------|
| Smoke | ~20 | Critical paths (app loads, report generates, PDF builds) |
| Unit | ~400 | logic.py, services, deep_research modules |
| Integration | ~150 | Multi-module flows (auth → analysis → report) |
| Regression | ~80 | Known bug fixes stay fixed |
| AppTest | ~46 | Streamlit widget rendering and interaction |
| Load | Locust | Non-LLM endpoints under concurrent load |
| Research eval | 27 | Router intent and grounded-answer release cases |
| **Total** | **800+** | **≥90% coverage gate** |

## 9. Contact

- **Owner**: Touseef Shaik (tshaik1990@gmail.com)
- **GitHub**: Touseef1949
- **HF Spaces**: tshaik1990
