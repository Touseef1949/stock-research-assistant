"""Shared data models for the production testing base."""

from __future__ import annotations

from dataclasses import dataclass

SCORE_ORDER = ["Fundamentals", "Technicals", "Sentiment", "Risk"]


@dataclass
class AgentResult:
    name: str
    content: str
    score: float
    source: str = "agent"
