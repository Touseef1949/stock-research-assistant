from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from core.models import AgentResult, SCORE_ORDER
from logic import (
    clamp_score,
    composite_score,
    local_scores,
    money,
    number,
    parse_score,
    pct,
    resolve_ticker,
    verdict_for_score,
)
from services.market_data import load_market_data
from yf_client import YFinanceRateLimitError

try:
    from agno.agent import Agent
    from agno.models.deepseek import DeepSeek
    from agno.tools.duckduckgo import DuckDuckGoTools
    from agno.tools.yfinance import YFinanceTools  # noqa: F401
except Exception:
    Agent = None
    DeepSeek = None
    DuckDuckGoTools = None
    YFinanceTools = None


def fallback_result(name: str, data: dict[str, Any], reason: str) -> AgentResult:
    score = local_scores(data["fundamentals"], data["technicals"])[name]
    f = data["fundamentals"]
    t = data["technicals"]
    details = {
        "Fundamentals": [
            f"Valuation: trailing P/E {number(f.get('trailing_pe'))}, price/book {number(f.get('price_to_book'))}.",
            f"Quality: ROE {pct(f.get('roe'))}, profit margin {pct(f.get('profit_margins'))}.",
            f"Balance sheet: debt/equity {number(f.get('debt_to_equity'))}.",
        ],
        "Technicals": [
            f"Trend is {t.get('trend')} with EMA20 at {number(t.get('ema20'))} and EMA50 at {number(t.get('ema50'))}.",
            f"RSI14 is {number(t.get('rsi'))}; MACD is {number(t.get('macd'))} versus signal {number(t.get('macd_signal'))}.",
            f"60-day support/resistance: \u20b9{t.get('support'):.2f} / \u20b9{t.get('resistance'):.2f}.",
        ],
        "Sentiment": [
            "News sentiment was not available in local mode.",
            f"Momentum proxy: 1Y return {number(t.get('return_1y_pct'), '%')}.",
            "Treat this as a neutral sentiment estimate until agent/news analysis is available.",
        ],
        "Risk": [
            f"Max 1Y drawdown is {number(t.get('max_drawdown_pct'), '%')}.",
            f"Annualized 60D volatility is {number(t.get('volatility_60d_pct'), '%')}.",
            f"Balance sheet risk proxy: debt/equity {number(f.get('debt_to_equity'))}.",
        ],
    }
    body = "\n".join(f"- {line}" for line in details[name])
    return AgentResult(
        name=name,
        score=score,
        source="local",
        content=f"SCORE: {score:.1f}/10\n{body}\n\nLocal fallback used: {reason}",
    )


def build_context(data: dict[str, Any]) -> str:
    f = data["fundamentals"]
    t = data["technicals"]
    return f"""
Symbol: {data['symbol']}
Company: {data['name']}
Price: \u20b9{data['price']:.2f}, day change {data['change']:+.2f} ({data['change_pct']:+.2f}%)
Market cap: {money(f.get('market_cap'))}
Trailing P/E: {number(f.get('trailing_pe'))}
Forward P/E: {number(f.get('forward_pe'))}
Price/book: {number(f.get('price_to_book'))}
ROE: {pct(f.get('roe'))}
Revenue growth: {pct(f.get('revenue_growth'))}
Profit margin: {pct(f.get('profit_margins'))}
Debt/equity: {number(f.get('debt_to_equity'))}
Dividend yield: {pct(f.get('dividend_yield'))}
Trend: {t.get('trend')}
RSI14: {number(t.get('rsi'))}
MACD: {number(t.get('macd'))}, signal: {number(t.get('macd_signal'))}
EMA20: {number(t.get('ema20'))}, EMA50: {number(t.get('ema50'))}
Support: \u20b9{t.get('support'):.2f}, resistance: \u20b9{t.get('resistance'):.2f}
1Y return: {number(t.get('return_1y_pct'), '%')}
Max drawdown: {number(t.get('max_drawdown_pct'), '%')}
60D annualized volatility: {number(t.get('volatility_60d_pct'), '%')}
""".strip()


def run_agent(agent: Any, prompt: str, dependencies: dict[str, Any]) -> str:
    response = agent.run(prompt, dependencies=dependencies)
    content = getattr(response, "content", response)
    return str(content or "").strip()


def agent_or_fallback(
    name: str,
    agent: Any,
    prompt: str,
    data: dict[str, Any],
    dependencies: dict[str, Any],
) -> AgentResult:
    try:
        content = run_agent(agent, prompt, dependencies)
        score = parse_score(content)
        if score is None:
            local = local_scores(data["fundamentals"], data["technicals"])[name]
            content = f"SCORE: {local:.1f}/10\n{content}\n\nScore parser fallback applied."
            score = local
        return AgentResult(name=name, content=content, score=score, source="agent")
    except Exception as exc:
        return fallback_result(name, data, f"{name} agent failed: {exc}")


def run_agent_pipeline(
    api_key: str,
    nse_symbol: str,
    data: dict[str, Any],
    progress_callback: Callable[[int, str | None], None] | None = None,
) -> dict[str, Any]:
    if Agent is None or DeepSeek is None:
        if progress_callback:
            progress_callback(70, "Assessing risk...")
            progress_callback(80, "Generating report...")
            progress_callback(95, None)
        return run_local_pipeline(data, "Agno is not installed or could not be imported.")

    model = DeepSeek(id="deepseek-v4-flash", api_key=api_key, temperature=0.2)
    # Avoid YFinanceTools here: it makes extra yfinance calls that can trigger
    # Yahoo rate limits on shared cloud IPs. We already pass full market context.
    news_tools = [DuckDuckGoTools()] if DuckDuckGoTools else []
    # When Yahoo Finance is rate-limited, use Screener fundamentals + web search.
    if data.get("source") == "screener_fallback":
        market_context = f"""
Symbol: {nse_symbol}
Company: {data.get('name', nse_symbol)}
Price: \u20b9{data['price']:.2f}
Source: Screener.in fallback (Yahoo Finance temporarily unavailable)
Market cap: {money(data['fundamentals'].get('market_cap'))}
Trailing P/E: {number(data['fundamentals'].get('trailing_pe'))}
Price/book: {number(data['fundamentals'].get('price_to_book'))}
ROE: {pct(data['fundamentals'].get('roe'))}
Revenue growth (3Y CAGR): {number(data['fundamentals'].get('revenue_growth'))}
Dividend yield: {pct(data['fundamentals'].get('dividend_yield'))}
Debt/equity: {number(data['fundamentals'].get('debt_to_equity'))}
Trend: {data['technicals'].get('trend')}
Note: Use web search (DuckDuckGo) for latest price action, news, and sector context.
""".strip()
    else:
        market_context = build_context(data)

    context = market_context
    dependencies = {"symbol": nse_symbol, "context": context}

    shared_instructions = [
        "Be concise and investment-research focused.",
        "Start the response with exactly: SCORE: X.X/10",
        "Use the provided market context. Do not invent unavailable figures.",
    ]
    agents = {
        "Fundamentals": Agent(
            name="Fundamentals",
            model=model,
            tools=news_tools,
            instructions=shared_instructions
            + ["Score valuation, quality, growth, profitability, and balance sheet strength. Use web search if key metrics are missing."],
        ),
        "Technicals": Agent(
            name="Technicals",
            model=model,
            tools=news_tools,
            instructions=shared_instructions
            + ["Score trend, momentum, levels, volume, and price action. Use web search for recent chart and news context when price history is unavailable."],
        ),
        "Sentiment": Agent(
            name="Sentiment",
            model=model,
            tools=news_tools,
            instructions=shared_instructions
            + ["Score recent company and sector news sentiment. Mention uncertainty when news is thin."],
        ),
        "Risk": Agent(
            name="Risk",
            model=model,
            tools=news_tools,
            instructions=shared_instructions
            + ["Score risk where a higher score means lower risk and better risk/reward."],
        ),
        "Coordinator": Agent(
            name="Coordinator",
            model=model,
            instructions=[
                "Write an executive stock research summary for a retail investor.",
                "Use the agent scores and explain the final stance in 4-6 bullets.",
                "Do not include a SCORE line.",
            ],
        ),
    }

    prompts = {
        "Fundamentals": f"Analyze fundamentals for {nse_symbol}.\n\nContext:\n{context}",
        "Technicals": f"Analyze technicals for {nse_symbol}.\n\nContext:\n{context}",
        "Sentiment": f"Analyze recent sentiment and news for {nse_symbol} listed in India.\n\nContext:\n{context}",
    }

    outputs: dict[str, AgentResult] = {}
    for name, prompt in prompts.items():
        if progress_callback:
            progress_callback(50, f"Running {name} analysis...")
        outputs[name] = agent_or_fallback(name, agents[name], prompt, data, dependencies)

    if progress_callback:
        progress_callback(70, "Assessing risk...")

    risk_prompt = (
        f"Analyze downside risk for {nse_symbol}.\n\nContext:\n{context}\n\n"
        f"Prior agent outputs:\n{format_agent_outputs(outputs)}"
    )
    outputs["Risk"] = agent_or_fallback("Risk", agents["Risk"], risk_prompt, data, dependencies)
    if progress_callback:
        progress_callback(80, "Generating report...")

    composite = composite_score({name: r.score for name, r in outputs.items()})
    verdict, _ = verdict_for_score(composite)
    coordinator_prompt = (
        f"Create the final executive summary for {nse_symbol} with verdict {verdict} "
        f"and composite score {composite:.1f}/10.\n\nContext:\n{context}\n\n"
        f"Agent outputs:\n{format_agent_outputs(outputs)}"
    )
    try:
        final_report = run_agent(agents["Coordinator"], coordinator_prompt, dependencies)
        if not final_report:
            raise RuntimeError("Coordinator returned an empty response.")
    except Exception as exc:
        final_report = build_local_summary(data, outputs, f"Coordinator failed: {exc}")

    if progress_callback:
        progress_callback(95, None)

    return {
        "mode": "agent",
        "agent_outputs": outputs,
        "final_report": final_report,
        "composite": composite,
        "verdict": verdict,
        "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
    }


def run_local_pipeline(data: dict[str, Any], reason: str) -> dict[str, Any]:
    outputs = {name: fallback_result(name, data, reason) for name in SCORE_ORDER}
    composite = composite_score({name: r.score for name, r in outputs.items()})
    verdict, _ = verdict_for_score(composite)
    return {
        "mode": "local",
        "agent_outputs": outputs,
        "final_report": build_local_summary(data, outputs, reason),
        "composite": composite,
        "verdict": verdict,
        "generated_at": datetime.now().strftime("%d %b %Y, %H:%M"),
    }


def format_agent_outputs(outputs: dict[str, AgentResult]) -> str:
    return "\n\n".join(
        f"{name} ({outputs[name].score:.1f}/10):\n{outputs[name].content}"
        for name in SCORE_ORDER
        if name in outputs
    )


def build_local_summary(data: dict[str, Any], outputs: dict[str, AgentResult], reason: str) -> str:
    composite = composite_score({name: r.score for name, r in outputs.items()})
    verdict, _ = verdict_for_score(composite)
    t = data["technicals"]
    f = data["fundamentals"]
    return f"""
**{verdict}** with a composite score of **{composite:.1f}/10**.

- Fundamentals score {outputs['Fundamentals'].score:.1f}/10, driven by P/E {number(f.get('trailing_pe'))}, ROE {pct(f.get('roe'))}, and debt/equity {number(f.get('debt_to_equity'))}.
- Technicals score {outputs['Technicals'].score:.1f}/10 with a {str(t.get('trend')).lower()} EMA setup, RSI {number(t.get('rsi'))}, and 1Y return {number(t.get('return_1y_pct'), '%')}.
- Sentiment score {outputs['Sentiment'].score:.1f}/10 uses local proxies because live news analysis was unavailable.
- Risk score {outputs['Risk'].score:.1f}/10 reflects max drawdown {number(t.get('max_drawdown_pct'), '%')} and volatility {number(t.get('volatility_60d_pct'), '%')}.

Local fallback mode: {reason}
""".strip()


def get_agent_output(result: dict[str, Any], data: dict[str, Any], name: str) -> AgentResult:
    outputs = result.get("agent_outputs") or {}
    output = outputs.get(name)
    if isinstance(output, AgentResult):
        return output
    if isinstance(output, dict):
        return AgentResult(
            name=name,
            content=str(output.get("content") or "No agent notes were returned."),
            score=clamp_score(output.get("score", local_scores(data["fundamentals"], data["technicals"])[name])),
            source=str(output.get("source") or "agent"),
        )
    return fallback_result(name, data, f"{name} agent output was unavailable.")


def run_analysis(
    symbol: str,
    api_key: str,
    progress_callback: Callable[[int, str | None], None] | None = None,
    resolved: dict[str, str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if resolved is None:
        resolved = resolve_ticker(symbol)
    nse_symbol = resolved["symbol"]
    if not nse_symbol:
        raise ValueError(
            f"We couldn't find a listed NSE ticker for '{symbol}'. "
            "Try the exact symbol (e.g. INFY) or a clearer company name."
        )

    try:
        data = load_market_data(nse_symbol)
    except YFinanceRateLimitError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not load market data for {nse_symbol}: {exc}")

    if progress_callback:
        progress_callback(20, "Running AI analysis...")
    if api_key:
        result = run_agent_pipeline(api_key, nse_symbol, data, progress_callback)
    else:
        if progress_callback:
            progress_callback(70, "Assessing risk...")
            progress_callback(80, "Generating report...")
            progress_callback(95, None)
        result = run_local_pipeline(data, "DEEPSEEK_API_KEY is missing.")
    return data, result
