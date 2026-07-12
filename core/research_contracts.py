"""Shared contracts for skill-driven, evidence-grounded research workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


Confidence = Literal["high", "medium", "low"]
RouteMode = Literal["direct", "workflow"]


def utc_now_iso() -> str:
    """Return a stable, timezone-aware timestamp for provenance records."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Evidence:
    """One sourced fact or deterministic calculation used by a workflow."""

    evidence_id: str
    metric: str
    value: Any
    source: str
    as_of: str
    unit: str = ""
    period: str = ""
    source_url: str = ""
    confidence: Confidence = "medium"
    kind: Literal["reported", "market", "calculated", "inferred"] = "reported"
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ToolResult:
    """Normalized response envelope for every research tool."""

    tool_name: str
    success: bool
    symbol: str
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence: list[Evidence] = field(default_factory=list)
    confidence: Confidence = "medium"
    is_fallback: bool = False
    warnings: list[str] = field(default_factory=list)
    as_of: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        return payload

    def audit_dict(self) -> dict[str, Any]:
        data_keys = sorted(str(key) for key in self.data.keys()) if isinstance(self.data, dict) else []
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "symbol": self.symbol,
            "source": self.source,
            "confidence": self.confidence,
            "is_fallback": self.is_fallback,
            "warnings": list(self.warnings),
            "as_of": self.as_of,
            "evidence_ids": [item.evidence_id for item in self.evidence],
            "data_keys": data_keys,
        }


@dataclass(frozen=True)
class RouteDecision:
    """Deterministic first-pass routing decision for a user request."""

    query: str
    mode: RouteMode
    skills: tuple[str, ...] = ()
    direct_tool: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TraceEvent:
    """Auditable action record; intentionally excludes hidden model reasoning."""

    event_type: Literal["route", "skill", "tool", "quality_gate", "synthesis", "validation", "warning"]
    name: str
    status: Literal["started", "completed", "failed", "skipped"]
    detail: str = ""
    timestamp: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass
class WorkflowResult:
    """Preparation output attached to reports and consumed by future agents/UI."""

    route: RouteDecision
    skill_catalog: list[dict[str, Any]]
    loaded_skills: list[dict[str, Any]]
    tool_results: list[ToolResult]
    trace: list[TraceEvent]
    evidence: list[Evidence]
    warnings: list[str]

    @staticmethod
    def _audit_skill(skill: dict[str, Any]) -> dict[str, Any]:
        procedure = str(skill.get("procedure") or "").strip()
        excerpt = procedure[:280].strip()
        if excerpt and len(procedure) > len(excerpt):
            excerpt = f"{excerpt}..."
        return {
            "name": str(skill.get("name") or ""),
            "description": str(skill.get("description") or ""),
            "when_to_use": str(skill.get("when_to_use") or ""),
            "command": str(skill.get("command") or ""),
            "required_tools": [str(item) for item in skill.get("required_tools") or []],
            "supporting_skills": [str(item) for item in skill.get("supporting_skills") or []],
            "procedure_excerpt": excerpt,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "route": self.route.to_dict(),
            "skill_catalog": self.skill_catalog,
            "loaded_skills": [self._audit_skill(item) for item in self.loaded_skills],
            "tool_results": [item.audit_dict() for item in self.tool_results],
            "trace": [item.to_dict() for item in self.trace],
            "evidence": [item.to_dict() for item in self.evidence],
            "warnings": self.warnings,
        }


@dataclass
class ResearchResponse:
    """Final answer plus the evidence and validation that produced it."""

    answer: str
    synthesis_mode: Literal["direct", "agent", "fallback"]
    workflow: WorkflowResult
    validation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "synthesis_mode": self.synthesis_mode,
            "workflow": self.workflow.to_dict(),
            "validation": self.validation,
        }
