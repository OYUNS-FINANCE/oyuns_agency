"""Composite scoring and the rank node. Pure Python: no LLM arithmetic."""

from __future__ import annotations

import structlog
from langgraph.runtime import Runtime

from app.agents.common.brief import IdeaBrief
from app.agents.skeptic.schemas import RUBRIC_DIMENSIONS, CritiqueScorecard
from app.core.config import RubricWeights
from app.graph.deps import GraphDeps
from app.graph.state import Phase1State

log = structlog.get_logger(__name__)


def composite_score(critique: CritiqueScorecard, weights: RubricWeights) -> float:
    """Weighted mean of the rubric scores (1-10). All-zero weights fall back to equal weights."""
    w: dict[str, float] = {d: float(getattr(weights, d)) for d in RUBRIC_DIMENSIONS}
    total = sum(w.values())
    if total == 0:
        w = dict.fromkeys(RUBRIC_DIMENSIONS, 1.0)
        total = float(len(RUBRIC_DIMENSIONS))
    scores = critique.score_map()
    return round(sum(scores[d] * w[d] for d in RUBRIC_DIMENSIONS) / total, 2)


def shortfall_message(viable: int, minimum: int, threshold: float, passes: int) -> str:
    return (
        f"Only {viable} idea(s) reached the quality threshold of {threshold:.1f} after "
        f"{passes} Scout pass(es), fewer than the {minimum} requested. The list shows only "
        "the ideas that passed; it has not been padded."
    )


async def rank_node(state: Phase1State, runtime: Runtime[GraphDeps]) -> Phase1State:
    settings = runtime.context.settings
    analyses = state.get("analyses", {})
    critiques = state.get("critiques", {})
    iteration = state.get("iteration", 0)
    scored = [o for o in state.get("opportunities", []) if o.id in analyses and o.id in critiques]
    scores = {o.id: composite_score(critiques[o.id], settings.rubric_weights) for o in scored}
    viable = sorted(
        (o for o in scored if scores[o.id] >= settings.quality_threshold),
        key=lambda o: (-scores[o.id], o.id),
    )
    briefs = [
        IdeaBrief(
            rank=i,
            composite_score=scores[o.id],
            opportunity=o,
            analysis=analyses[o.id],
            critique=critiques[o.id],
        )
        for i, o in enumerate(viable[: settings.max_briefs], start=1)
    ]
    enough = len(viable) >= settings.min_viable_ideas
    loop_back = not enough and iteration < settings.max_scout_iterations
    shortfall = (
        None
        if enough or loop_back
        else shortfall_message(
            len(viable), settings.min_viable_ideas, settings.quality_threshold, iteration
        )
    )
    log.info(
        "rank.done",
        scored=len(scored),
        viable=len(viable),
        iteration=iteration,
        loop_back=loop_back,
    )
    return {
        "composite_scores": scores,
        "briefs": briefs,
        "viable_count": len(viable),
        "loop_back": loop_back,
        "shortfall": shortfall,
    }
