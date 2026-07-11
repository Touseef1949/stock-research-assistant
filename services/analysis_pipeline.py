from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
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
    ticker_not_found_message,
    verdict_for_score,
)
from services.market_data import load_market_data
from services.research_orchestrator import run_research_request
from core.research_router import route_research_query
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
    # Quick report mode: keep the pipeline fast and deterministic.
    # Live web/news tools caused repeated no-result retries that dominated latency
    # on cloud deployments, so this path relies on the supplied market context only.
    research_tools: list[Any] = []
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
            tools=[],
            instructions=shared_instructions
            + ["Score valuation, quality, growth, profitability, and balance sheet strength from the provided context. Use only the supplied data; do not browse the web unless this prompt explicitly says data is missing."],
        ),
        "Technicals": Agent(
            name="Technicals",
            model=model,
            tools=[],
            instructions=shared_instructions
            + ["Score trend, momentum, levels, volume, and price action from the provided context. Use only the supplied data; do not browse the web unless this prompt explicitly says price history is unavailable."],
        ),
        "Sentiment": Agent(
            name="Sentiment",
            model=model,
            tools=research_tools,
            instructions=shared_instructions
            + ["Score sentiment from the provided context and recent price/momentum proxies only. Be explicit that quick-report mode does not fetch live news."],
        ),
        "Risk": Agent(
            name="Risk",
            model=model,
            tools=research_tools,
            instructions=shared_instructions
            + ["Score risk where a higher score means lower risk and better risk/reward. Use only the supplied context and prior agent outputs; quick-report mode does not browse the web."],
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
    if progress_callback:
        progress_callback(50, "Running AI analysis...")

    with ThreadPoolExecutor(max_workers=len(prompts)) as executor:
        futures = {
            executor.submit(agent_or_fallback, name, agents[name], prompt, data, dependencies): name
            for name, prompt in prompts.items()
        }
        completed: dict[str, AgentResult] = {}
        for future in as_completed(futures):
            name = futures[future]
            completed[name] = future.result()

    for name in prompts:
        outputs[name] = completed[name]

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
    research_query: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if resolved is None:
        resolved = resolve_ticker(symbol)
    nse_symbol = resolved["symbol"]
    if not nse_symbol:
        raise ValueError(ticker_not_found_message(symbol))

    try:
        data = load_market_data(nse_symbol)
    except YFinanceRateLimitError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Could not load market data for {nse_symbol}: {exc}")

    if progress_callback:
        progress_callback(20, "Running AI analysis...")
    workflow_query = research_query or f"/snapshot {nse_symbol}"
    initial_route = route_research_query(workflow_query)
    if initial_route.mode == "direct":
        if progress_callback:
            progress_callback(70, "Preparing direct evidence...")
            progress_callback(95, None)
        result = run_local_pipeline(data, "Direct metric request; expensive agent synthesis was skipped.")
    elif api_key:
        result = run_agent_pipeline(api_key, nse_symbol, data, progress_callback)
    else:
        if progress_callback:
            progress_callback(70, "Assessing risk...")
            progress_callback(80, "Generating report...")
            progress_callback(95, None)
        result = run_local_pipeline(data, "DEEPSEEK_API_KEY is missing.")
    research_response = run_research_request(
        workflow_query,
        data,
        api_key=api_key,
        base_result=result,
    )
    result["base_report"] = result.get("final_report", "")
    result["final_report"] = research_response.answer
    result["research_request"] = workflow_query
    result["research_workflow"] = research_response.workflow.to_dict()
    result["research_validation"] = research_response.validation
    result["research_synthesis_mode"] = research_response.synthesis_mode
    return data, result
