"""Run deterministic routing and evidence-grounding release evaluations."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.research_router import route_research_query  # noqa: E402
from core.skills import SkillRegistry  # noqa: E402
from services.research_orchestrator import run_research_request  # noqa: E402


CASES_PATH = Path(__file__).resolve().parent / "workflow_cases.yaml"


def _market_data() -> dict[str, Any]:
    return {
        "symbol": "TCS.NS",
        "name": "Tata Consultancy Services",
        "price": 4000.0,
        "change": 10.0,
        "change_pct": 0.25,
        "source": "eval_fixture",
        "as_of": "2026-07-11T10:00:00+05:30",
        "history": list(range(100)),
        "info": {
            "currentPrice": 4000.0,
            "targetMeanPrice": 4400.0,
            "targetHighPrice": 5000.0,
            "targetLowPrice": 3500.0,
            "numberOfAnalystOpinions": 20,
            "recommendationKey": "buy",
        },
        "news": [
            {
                "title": "TCS publishes quarterly operating update",
                "publisher": "Exchange News",
                "providerPublishTime": 1783754400,
                "link": "https://finance.yahoo.com/news/tcs-update",
            }
        ],
        "screener_data": {
            "success": True,
            "source": "screener",
            "data": {
                "symbol": "TCS",
                "url": "https://www.screener.in/company/TCS/",
                "years": ["Mar 2026"],
                "quarterly": {"sales": [100]},
                "profit_loss": {"sales": [400]},
                "balance_sheet": {},
                "cash_flow": {},
                "documents": {"transcripts": [], "annual_reports": [], "announcements": []},
                "peers": [],
            },
            "warnings": [],
        },
        "fundamentals": {
            "market_cap": 14_000_000,
            "trailing_pe": 30.0,
            "forward_pe": 27.0,
            "price_to_book": 12.0,
            "roe": 0.42,
            "revenue_growth": 0.08,
            "profit_margins": 0.19,
            "debt_to_equity": 0.1,
        },
        "technicals": {
            "trend": "Bullish",
            "rsi": 56.0,
            "support": 3850.0,
            "resistance": 4100.0,
            "return_1y_pct": 11.0,
            "max_drawdown_pct": -18.0,
            "volatility_60d_pct": 24.0,
        },
    }


def load_cases(path: Path = CASES_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def evaluate_routing(config: dict[str, Any]) -> dict[str, Any]:
    registry = SkillRegistry()
    failures = []
    cases = config.get("cases") or []
    for case in cases:
        route = route_research_query(str(case["query"]), registry)
        passed = route.mode == case["mode"]
        if case.get("direct_tool"):
            passed = passed and route.direct_tool == case["direct_tool"]
        if case.get("skill"):
            passed = passed and case["skill"] in route.skills
        if not passed:
            failures.append({"case": case, "actual": route.to_dict()})
    accuracy = (len(cases) - len(failures)) / len(cases) if cases else 0.0
    minimum = float(config.get("minimum_routing_accuracy", 0.9))
    return {
        "passed": accuracy >= minimum,
        "accuracy": accuracy,
        "minimum": minimum,
        "case_count": len(cases),
        "failures": failures,
    }


def evaluate_grounding() -> dict[str, Any]:
    data = _market_data()
    requests = [
        "What is TCS current price?",
        "/snapshot TCS",
        "/fundamentals TCS",
        "/entry TCS",
        "/valuation TCS",
        "/risks TCS",
        "/thesis TCS",
        "/catalysts TCS",
    ]
    failures = []
    for query in requests:
        response = run_research_request(query, data, api_key="")
        if not response.validation.get("valid"):
            failures.append({"query": query, "validation": response.validation})
    return {
        "passed": not failures,
        "case_count": len(requests),
        "failures": failures,
    }


def run_all_evals() -> dict[str, Any]:
    config = load_cases()
    routing = evaluate_routing(config)
    grounding = evaluate_grounding()
    return {"passed": routing["passed"] and grounding["passed"], "routing": routing, "grounding": grounding}


def main() -> int:
    result = run_all_evals()
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
