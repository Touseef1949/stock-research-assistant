"""Release-gate tests for workflow routing and evidence grounding."""

from eval.run_research_evals import (
    evaluate_grounding,
    evaluate_routing,
    load_cases,
    run_all_evals,
)


def test_routing_eval_meets_release_threshold():
    result = evaluate_routing(load_cases())
    assert result["accuracy"] >= 0.90, result["failures"]
    assert result["passed"] is True


def test_grounding_eval_passes_every_case():
    result = evaluate_grounding()
    assert result["passed"] is True, result["failures"]


def test_combined_research_eval_gate_passes():
    assert run_all_evals()["passed"] is True
