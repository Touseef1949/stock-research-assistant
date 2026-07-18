#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"

"${PYTHON_BIN}" -m ruff format --check core services research_tools eval scripts
"${PYTHON_BIN}" -m ruff check core services research_tools eval scripts
"${PYTHON_BIN}" -m mypy core/models.py core/research_contracts.py \
  core/research_router.py core/research_validation.py
"${PYTHON_BIN}" -m py_compile app.py logic.py payment.py ui.py yf_client.py
"${PYTHON_BIN}" -m pytest tests/ -q --tb=short --cov=. \
  --cov-report=term-missing:skip-covered --cov-fail-under=90 \
  -k "not slow" --timeout=120
"${PYTHON_BIN}" eval/run_research_evals.py
