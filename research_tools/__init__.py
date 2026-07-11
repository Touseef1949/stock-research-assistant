"""Deterministic, normalized tools used by stock-research skills."""

from research_tools.market_context import TOOL_FUNCTIONS
from research_tools.external_research import EXTERNAL_TOOL_FUNCTIONS

TOOL_FUNCTIONS = {**TOOL_FUNCTIONS, **EXTERNAL_TOOL_FUNCTIONS}

__all__ = ["TOOL_FUNCTIONS"]
