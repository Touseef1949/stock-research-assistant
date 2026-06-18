# Production Test Base Refactor Spec

## Goal
Turn Stock Research Assistant's current high-coverage test suite into a reusable production-scale app testing base by splitting the monolithic `app.py` into testable service modules while preserving app behavior.

## Current state

| Area | Current implementation | Problem |
| --- | --- | --- |
| Streamlit entrypoint | `app.py` contains CSS, state init, data fetching, analysis, PDF, auth wrappers, render functions, report persistence, history, main orchestration | `app.py` is too large and Streamlit-heavy; coverage stalls even after many tests |
| Tests | 653 passing / 12 skipped, ~94% overall coverage | Good foundation, but many tests still monkeypatch `app` internals instead of module-level service contracts |
| Production code | Existing production code works; recent work added tests only | Refactor must preserve behavior and import compatibility where practical |

## Proposed module layout

Create these modules/packages:

```text
core/
  __init__.py
  models.py              # AgentResult, SCORE_ORDER, constants shared by tests/services
  formatting.py          # markdown/html/report text helpers where independent from Streamlit
services/
  __init__.py
  market_data.py         # Screener/web/yfinance market-data fallback pipeline
  analysis_pipeline.py   # fallback_result, build_context, run_agent*, run_local_pipeline, run_analysis
  report_history.py      # report file naming, json_safe, restore_dataframe, save/load history
ui_sections/
  __init__.py
  auth.py                # render_sidebar_access/auth_gate/research_setup/signout wrappers if safe
  deep_research_tab.py   # _deep_* render helpers and render_deep_research_tab
```

Keep `app.py` as the Streamlit composition layer:
- CSS/theme injection
- init_state
- main()
- high-level layout composition
- imports/re-exports compatibility names during transition

## Refactor rules

1. Do NOT change user-visible behavior.
2. Do NOT touch payment activation/security logic except imports if required.
3. Preserve existing tests or update tests to target the new module contracts.
4. No real network calls in tests.
5. No fake 100% via blanket coverage exclusions.
6. Keep AppTest/network skips only where technically justified.
7. Prefer pure functions and dependency injection in new modules.
8. `app.py` may re-export compatibility names during transition, but new tests should target service modules directly.

## Implementation phases

### Phase 1 — safest extraction
Extract non-Streamlit/pure or mostly pure code:
- `AgentResult`, `SCORE_ORDER` -> `core.models`
- report/history helpers -> `services.report_history`
- analysis helpers -> `services.analysis_pipeline`
- market data helpers -> `services.market_data`

Acceptance:
- `python3 -m py_compile app.py services/*.py core/*.py`
- `pytest tests/ -q` passes
- coverage remains >= 94%

### Phase 2 — UI section extraction
Extract Streamlit-heavy groups behind small module APIs:
- deep research tab renderers
- auth/research setup/signout renderers

Acceptance:
- Existing UI behavior preserved
- Tests updated to mock module-level Streamlit dependencies cleanly

### Phase 3 — production testing standard
Add/adjust coverage config only for legitimate entrypoint/UI-only code:
- exclude `if __name__ == "__main__"`
- exclude `main()` only if covered by smoke tests instead
- do NOT exclude service modules

Acceptance target:
- service modules >= 95%
- critical payment/auth/security >= 95%
- overall meaningful coverage >= 95% without gaming
- full suite green

## Verification command

```bash
/usr/local/bin/python3 -m py_compile app.py logic.py payment.py yf_client.py deep_research/*.py core/*.py services/*.py ui_sections/*.py
/usr/local/bin/python3 -m pytest tests/ --cov=. --cov-report=term-missing:skip-covered -q
```

## Rollback safety
If extraction breaks too many tests, stop after Phase 1 and report remaining blockers instead of forcing a risky rewrite.
