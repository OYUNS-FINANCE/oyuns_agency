"""Market Analyst node: one search-backed MarketAnalysis per opportunity not yet analysed."""

from __future__ import annotations

from collections.abc import Callable

import structlog
from langgraph.runtime import Runtime

from app.agents.analyst import prompts
from app.agents.analyst.schemas import MarketAnalysis, MarketAnalysisOutput
from app.agents.common.context import gather_bounded, render_run_context
from app.agents.common.untrusted import wrap_untrusted
from app.agents.scout.schemas import RawOpportunity
from app.graph.deps import GraphDeps
from app.graph.state import Phase1State
from app.providers.llm.base import ChatMessage, LLMOutputError, LLMRequest, UsageRecord
from app.providers.search.base import SearchResult

log = structlog.get_logger(__name__)

AGENT = "analyst"
RESULTS_PER_QUERY = 4


def analyst_queries(opp: RawOpportunity) -> list[str]:
    return [
        f"{opp.title} market size",
        f"{opp.industry} {opp.target_customer} competitors pricing",
        f"{opp.problem[:80]} number of businesses",
    ]


def check_sources(allowed: set[str]) -> Callable[[MarketAnalysisOutput], None]:
    def check(out: MarketAnalysisOutput) -> None:
        cited = {str(f.source_url) for f in out.figures() if f.source_url is not None}
        cited |= {str(c.url) for c in out.competitors if c.url is not None}
        bad = sorted(cited - allowed)
        if bad:
            raise ValueError(
                f"these URLs are not in the search results: {bad}. Use a URL from the "
                "results, or drop the URL and give an explicit assumption instead."
            )

    return check


async def _analyse(
    opp: RawOpportunity, run_context: str, deps: GraphDeps
) -> tuple[MarketAnalysis | None, list[UsageRecord]]:
    """Returns (None, usage) when the model cannot produce a valid analysis: the idea is
    then left unanalysed and is never ranked, rather than failing the whole run."""
    batches = [
        await deps.search.search(q, max_results=RESULTS_PER_QUERY) for q in analyst_queries(opp)
    ]
    results: dict[str, SearchResult] = {}
    for batch in batches:
        for r in batch:
            results.setdefault(str(r.url), r)
    signals = "\n".join(f"- [{s.category}] {s.url}: {s.evidence}" for s in opp.signals)
    request = LLMRequest(
        agent=AGENT,
        model=deps.settings.analyst_model,
        system=prompts.SYSTEM_V1,
        messages=[
            ChatMessage(
                role="user",
                content=(
                    f"{run_context}\n\nOpportunity {opp.id}: {opp.title}\n"
                    f"One-liner: {opp.one_liner}\nProblem: {opp.problem}\n"
                    f"Target customer: {opp.target_customer}\nIndustry: {opp.industry}\n"
                    f"Business model: {opp.business_model}\n"
                    f"Scout signals (summaries of earlier results):\n{signals}\n\n"
                    f"Search results:\n{wrap_untrusted(list(results.values()))}"
                ),
            )
        ],
        output_type=MarketAnalysisOutput,
        validator=check_sources(set(results)),
    )
    try:
        result = await deps.llm.generate(request)
    except LLMOutputError as exc:
        log.warning("analyst.idea_failed", opportunity_id=opp.id, error=exc.last_error)
        return None, exc.usage
    analysis = MarketAnalysis(**result.output.model_dump(), opportunity_id=opp.id)
    return analysis, result.usage


async def analyst_node(state: Phase1State, runtime: Runtime[GraphDeps]) -> Phase1State:
    deps = runtime.context
    done = state.get("analyses", {})
    todo = [o for o in state.get("opportunities", []) if o.id not in done]
    run_context = render_run_context(state["run_input"])
    outcomes = await gather_bounded(
        (_analyse(o, run_context, deps) for o in todo), deps.settings.agent_concurrency
    )
    analyses = {a.opportunity_id: a for a, _ in outcomes if a is not None}
    usage = [u for _, us in outcomes for u in us]
    estimates = sum(f.is_estimate for a in analyses.values() for f in a.figures())
    log.info("analyst.done", analysed=len(analyses), estimated_figures=estimates)
    return {"analyses": analyses, "usage": usage}
