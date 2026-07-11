"""Prepare auditable skill/tool context for the stock analysis pipeline."""

from __future__ import annotations

from typing import Any

from core.research_contracts import TraceEvent, WorkflowResult
from core.research_router import route_research_query
from core.skills import SkillRegistry
from research_tools import TOOL_FUNCTIONS


def prepare_research_workflow(
    query: str,
    market_data: dict[str, Any],
    registry: SkillRegistry | None = None,
) -> WorkflowResult:
    """Route a query, load procedures, execute available deterministic tools."""
    registry = registry or SkillRegistry()
    route = route_research_query(query, registry)
    trace = [TraceEvent("route", route.direct_tool or ",".join(route.skills), "completed", route.reason)]
    loaded_skills: list[dict[str, Any]] = []
    requested_tools: list[str] = []

    if route.mode == "direct":
        requested_tools.append(route.direct_tool)
    else:
        for skill_name in route.skills:
            skill = registry.get(skill_name)
            if skill is None:
                trace.append(TraceEvent("skill", skill_name, "failed", "Skill was not found"))
                continue
            loaded_skills.append(skill.loaded_entry())
            requested_tools.extend(skill.required_tools)
            trace.append(TraceEvent("skill", skill.name, "completed", "Procedure loaded on demand"))

    tool_results = []
    warnings: list[str] = []
    for tool_name in dict.fromkeys(requested_tools):
        tool = TOOL_FUNCTIONS.get(tool_name)
        if tool is None:
            warning = f"Tool '{tool_name}' is declared by the workflow but is not available yet."
            warnings.append(warning)
            trace.append(TraceEvent("tool", tool_name, "skipped", warning))
            continue
        try:
            result = tool(market_data)
            tool_results.append(result)
            warnings.extend(result.warnings)
            trace.append(TraceEvent("tool", tool_name, "completed" if result.success else "failed", result.source))
            if result.confidence == "low":
                trace.append(TraceEvent("quality_gate", tool_name, "completed", "Low-confidence result; conclusions must be qualified"))
        except Exception as exc:
            warning = f"{tool_name} failed: {exc}"
            warnings.append(warning)
            trace.append(TraceEvent("tool", tool_name, "failed", str(exc)))

    evidence = [item for result in tool_results for item in result.evidence]
    return WorkflowResult(
        route=route,
        skill_catalog=registry.catalog(),
        loaded_skills=loaded_skills,
        tool_results=tool_results,
        trace=trace,
        evidence=evidence,
        warnings=list(dict.fromkeys(warnings)),
    )
