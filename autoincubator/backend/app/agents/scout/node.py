"""Trend Scout node: plan searches → run them → extract, filter and dedup candidates."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable

import structlog
from langgraph.runtime import Runtime

from app.agents.common.context import gather_bounded, render_run_context
from app.agents.common.schemas import RunInput
from app.agents.common.untrusted import wrap_untrusted
from app.agents.scout import prompts
from app.agents.scout.schemas import (
    RawOpportunity,
    ScoutCandidate,
    ScoutOutput,
    ScoutQueryPlan,
)
from app.graph.deps import GraphDeps
from app.graph.state import Phase1State
from app.providers.llm.base import ChatMessage, LLMRequest, UsageRecord
from app.providers.search.base import SearchResult

log = structlog.get_logger(__name__)

AGENT = "scout"
RESULTS_PER_QUERY = 5
MAX_INDUSTRY_SHARE_MODE_B = 3
MIN_SIGNAL_STRENGTH = 5
MIN_NOVELTY = 4


def _check_plan_diversity(plan: ScoutQueryPlan) -> None:
    counts = Counter(q.industry.strip().lower() for q in plan.queries)
    crowded = [i for i, n in counts.items() if n > MAX_INDUSTRY_SHARE_MODE_B]
    if crowded:
        raise ValueError(
            f"industries {crowded} appear in more than {MAX_INDUSTRY_SHARE_MODE_B} queries"
        )
    if len({q.category for q in plan.queries}) < 4:
        raise ValueError("queries must cover at least four signal categories")


def _check_urls(allowed: set[str]) -> Callable[[ScoutOutput], None]:
    def check(out: ScoutOutput) -> None:
        bad = sorted({str(s.url) for c in out.candidates for s in c.signals} - allowed)
        if bad:
            raise ValueError(f"signals cite URLs that are not in the search results: {bad}")

    return check


def _excluded(candidate: ScoutCandidate, run_input: RunInput) -> bool:
    industry = candidate.industry.lower()
    return any(
        ex.strip().lower() and ex.strip().lower() in industry
        for ex in run_input.constraints.excluded_industries
    )


def _passes_quality_filter(c: ScoutCandidate) -> bool:
    return (
        not c.is_generic
        and c.signal_strength >= MIN_SIGNAL_STRENGTH
        and c.novelty_score >= MIN_NOVELTY
    )


async def scout_node(state: Phase1State, runtime: Runtime[GraphDeps]) -> Phase1State:
    deps = runtime.context
    settings = deps.settings
    run_input = state["run_input"]
    iteration = state.get("iteration", 0) + 1
    existing = state.get("opportunities", [])
    usage: list[UsageRecord] = []
    run_context = render_run_context(run_input)

    plan_prompt = prompts.MODE_A_PLAN_V1 if run_input.mode == "seeded" else prompts.MODE_B_PLAN_V1
    plan_result = await deps.llm.generate(
        LLMRequest(
            agent=f"{AGENT}.plan",
            model=settings.scout_model,
            system=plan_prompt,
            messages=[
                ChatMessage(role="user", content=f"{run_context}\n\nScout pass: {iteration}")
            ],
            output_type=ScoutQueryPlan,
            max_tokens=4_000,
            validator=_check_plan_diversity if run_input.mode == "autonomous" else None,
        )
    )
    usage += plan_result.usage
    queries = plan_result.output.queries

    batches = await gather_bounded(
        (deps.search.search(q.query, max_results=RESULTS_PER_QUERY) for q in queries),
        settings.agent_concurrency,
    )
    results: dict[str, SearchResult] = {}
    for batch in batches:
        for r in batch:
            results.setdefault(str(r.url), r)

    already = "\n".join(f"- {o.title}: {o.one_liner}" for o in existing) or "- none"
    query_list = "\n".join(f"- [{q.category}] {q.query}" for q in queries)
    extract_result = await deps.llm.generate(
        LLMRequest(
            agent=f"{AGENT}.extract",
            model=settings.scout_model,
            system=prompts.EXTRACT_V1.format(target=settings.scout_target_candidates),
            messages=[
                ChatMessage(
                    role="user",
                    content=(
                        f"{run_context}\n\nQueries run:\n{query_list}\n\n"
                        f"Already proposed (do not repeat):\n{already}\n\n"
                        f"Search results:\n{wrap_untrusted(list(results.values()))}"
                    ),
                )
            ],
            output_type=ScoutOutput,
            validator=_check_urls(set(results)),
        )
    )
    usage += extract_result.usage
    candidates = extract_result.output.candidates

    filtered = [c for c in candidates if _passes_quality_filter(c) and not _excluded(c, run_input)]
    unique = deps.dedup.filter_new(filtered, existing)
    offset = len(existing)
    new = [
        RawOpportunity(**c.model_dump(), id=f"opp-{offset + i + 1:02d}", iteration=iteration)
        for i, c in enumerate(unique)
    ]
    log.info(
        "scout.done",
        iteration=iteration,
        queries=len(queries),
        results=len(results),
        proposed=len(candidates),
        kept=len(new),
    )
    return {"iteration": iteration, "opportunities": new, "usage": usage}
