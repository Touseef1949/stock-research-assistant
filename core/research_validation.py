"""Validate user-visible evidence citations without exposing model reasoning."""

from __future__ import annotations

import re
from typing import Any, Iterable

from core.research_contracts import Evidence


CITATION_PATTERN = re.compile(r"\[([A-Za-z0-9_.:-]+)\]")
NUMERIC_CLAIM_PATTERN = re.compile(r"(?:₹|Rs\.?\s*)?\b\d[\d,]*(?:\.\d+)?(?:%|x|/10)?\b")


def validate_evidence_citations(answer: str, evidence: Iterable[Evidence]) -> dict[str, Any]:
    """Check that citations resolve and numeric research claims are sourced."""
    text = str(answer or "")
    valid_ids = {item.evidence_id for item in evidence}
    cited_ids = list(dict.fromkeys(CITATION_PATTERN.findall(text)))
    invalid_ids = [item for item in cited_ids if item not in valid_ids]
    has_numeric_claims = bool(NUMERIC_CLAIM_PATTERN.search(text))
    warnings: list[str] = []
    if invalid_ids:
        warnings.append(f"Unknown evidence citations: {', '.join(invalid_ids)}")
    if has_numeric_claims and not cited_ids:
        warnings.append("The answer contains numeric claims but no evidence citations.")
    if not valid_ids:
        warnings.append("No structured evidence was available to validate the answer.")
    return {
        "valid": not invalid_ids and not (has_numeric_claims and not cited_ids) and bool(valid_ids),
        "cited_evidence_ids": cited_ids,
        "invalid_evidence_ids": invalid_ids,
        "available_evidence_count": len(valid_ids),
        "warnings": warnings,
    }
