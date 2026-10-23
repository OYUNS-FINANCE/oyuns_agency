"""Devil's Advocate node: one rubric scorecard per analysed opportunity not yet critiqued."""

from __future__ import annotations

import time

import structlog
from langgraph.runtime import Runtime

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.common.context import elapsed_ms, gather_bounded, render_run_context
from app.agents.scout.schemas import RawOpportunity
from app.agents.skeptic import prompts
from app.agents.skeptic.schemas import CritiqueOutput, CritiqueScorecard
from app.events.schema import AgentCompleted, AgentStarted, AgentThought
from app.graph.deps import GraphDeps
from app.graph.state import Phase1State
from app.providers.llm.base import ChatMessage, LLMOutputError, LLMRequest, UsageRecord

log = structlog.get_logger(__name__)

AGENT = "skeptic"


async def critique_opportunity(
    opp: RawOpportunity, analysis: MarketAnalysis, run_context: str, deps: GraphDeps
) -> tuple[CritiqueScorecard | None, list[UsageRecord]]:
    """Returns (None, usage) when no valid scorecard is produced; the idea is then unranked."""
    request = LLMRequest(
        agent=AGENT,
        model=deps.settings.skeptic_model,
        system=prompts.SYSTEM_V1,
        messages=[
            ChatMessage(
                role="user",
                content=(
                    f"{run_context}\n\nOpportunity {opp.id}:\n"
                    f"{opp.model_dump_json(exclude={'id', 'iteration'})}\n\n"
                    f"Market analysis:\n{analysis.model_dump_json(exclude={'opportunity_id'})}"
                ),
            )
        ],
        output_type=CritiqueOutput,
        max_tokens=8_000,
    )
    try:
        result = await deps.llm.generate(request)
    except LLMOutputError as exc:
        log.warning("skeptic.idea_failed", opportunity_id=opp.id, error=exc.last_error)
        await deps.events.emit(
            AgentThought(text=f"Could not produce a valid scorecard for {opp.id}; skipping it."),
            agent=AGENT,
        )
        return None, exc.usage
    return CritiqueScorecard(**result.output.model_dump(), opportunity_id=opp.id), result.usage


async def skeptic_node(state: Phase1State, runtime: Runtime[GraphDeps]) -> Phase1State:
    deps = runtime.context
    analyses = state.get("analyses", {})
    done = state.get("critiques", {})
    todo = [o for o in state.get("opportunities", []) if o.id in analyses and o.id not in done]
    run_context = render_run_context(state["run_input"])
    started = time.monotonic()
    await deps.events.emit(AgentStarted(node="skeptic", items=len(todo)), agent=AGENT)
    outcomes = await gather_bounded(
        (critique_opportunity(o, analyses[o.id], run_context, deps) for o in todo),
        deps.settings.agent_concurrency,
    )
    critiques = {c.opportunity_id: c for c, _ in outcomes if c is not None}
    usage = [u for _, us in outcomes for u in us]
    await deps.events.emit(
        AgentCompleted(
            node="skeptic",
            duration_ms=elapsed_ms(started),
            summary={"critiqued": len(critiques), "failed": len(todo) - len(critiques)},
        ),
        agent=AGENT,
    )
    log.info("skeptic.done", critiqued=len(critiques))
    return {"critiques": critiques, "usage": usage}
