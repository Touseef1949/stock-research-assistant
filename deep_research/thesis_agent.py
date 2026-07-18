"""LLM thesis generator for the Deep Research module."""

from __future__ import annotations

import json
from typing import Any

from core.ai_policy import TEXT_MODEL_ID

def _compact(obj: Any, max_chars: int = 12000) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False, default=str, indent=2)
    except Exception:
        text = str(obj)
    if len(text) > max_chars:
        return text[:max_chars] + "\n... [truncated]"
    return text


def _fallback_thesis(symbol: str, reason: str | None = None) -> dict[str, Any]:
    suffix = f" Reason: {reason}" if reason else ""
    return {
        "one_line_thesis": f"{symbol} requires manual review because the automated thesis agent was unavailable.{suffix}",
        "company_overview": "Company overview unavailable from the thesis agent. Use the peer table, risk flags, valuation, and financial trends for manual review.",
        "bull_case": [
            "Bull case unavailable from LLM fallback; check revenue growth, margin stability, ROE/ROCE, and valuation upside.",
        ],
        "bear_case": [
            "Bear case unavailable from LLM fallback; review leverage, cash conversion, governance, and valuation premium risks.",
        ],
        "key_catalysts": ["Catalysts unavailable from LLM fallback."],
        "market_missing": "Unavailable. Run again with a valid DeepSeek API key for a structured thesis.",
    }


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except Exception:
            return None
    return None


def generate_investment_thesis(
    symbol: str,
    market_data: dict[str, Any],
    peer_comparison: dict[str, Any],
    financial_trends: dict[str, Any],
    risk_flags: dict[str, Any],
    valuation: dict[str, Any],
    governance: dict[str, Any],
    api_key: str | None = None,
) -> dict[str, Any]:
    """Generate a structured thesis using Agno + DeepSeek, with fallback.

    The function accepts `api_key` as an optional final argument so the existing
    app can pass the same DeepSeek key without changing earlier call sites.
    """
    warnings: list[str] = []
    if not api_key:
        return {
            "success": True,
            "source": "fallback",
            "data": _fallback_thesis(symbol, "DeepSeek API key not provided"),
            "warnings": ["DeepSeek API key not provided; returned fallback thesis"],
        }

    try:
        from agno.agent import Agent
        from agno.models.deepseek import DeepSeek
    except Exception as exc:
        return {
            "success": True,
            "source": "fallback",
            "data": _fallback_thesis(symbol, f"Agno/DeepSeek import failed: {exc}"),
            "warnings": [f"Agno/DeepSeek import failed: {exc}"],
        }

    context = {
        "symbol": symbol,
        "market_data": market_data,
        "peer_comparison": peer_comparison.get("data", peer_comparison),
        "financial_trends_summary": financial_trends.get("data", {}).get("summary", []),
        "risk_flags": risk_flags.get("data", risk_flags),
        "valuation": valuation.get("data", valuation),
        "governance": governance.get("data", governance),
    }

    prompt = f"""
You are an institutional equity research analyst for Indian listed equities.
Use only the structured context below. Do not invent facts.

Return ONLY valid JSON with exactly these keys:
- one_line_thesis: string
- company_overview: string
- bull_case: array of 3-5 strings
- bear_case: array of 3-5 strings
- key_catalysts: array of 3-5 strings
- market_missing: string

Context:
{_compact(context)}
""".strip()

    try:
        agent = Agent(
            model=DeepSeek(id=TEXT_MODEL_ID, api_key=api_key),
            instructions=[
                "You produce concise, evidence-grounded Indian equity research.",
                "Return JSON only. Do not include markdown fences.",
                "Avoid investment advice language; frame as research observations.",
            ],
            markdown=False,
        )
        response = agent.run(prompt)
        content = getattr(response, "content", response)
        parsed = _extract_json(str(content))
        if not parsed:
            warnings.append("DeepSeek response was not valid JSON; returned fallback thesis")
            return {"success": True, "source": "fallback", "data": _fallback_thesis(symbol, "LLM returned non-JSON output"), "warnings": warnings}

        clean = {
            "one_line_thesis": str(parsed.get("one_line_thesis") or ""),
            "company_overview": str(parsed.get("company_overview") or ""),
            "bull_case": [str(item) for item in parsed.get("bull_case", [])][:5],
            "bear_case": [str(item) for item in parsed.get("bear_case", [])][:5],
            "key_catalysts": [str(item) for item in parsed.get("key_catalysts", [])][:5],
            "market_missing": str(parsed.get("market_missing") or ""),
        }
        return {"success": True, "source": "deepseek", "data": clean, "warnings": warnings}
    except Exception as exc:
        return {
            "success": True,
            "source": "fallback",
            "data": _fallback_thesis(symbol, str(exc)),
            "warnings": [f"DeepSeek thesis generation failed: {exc}"],
        }
