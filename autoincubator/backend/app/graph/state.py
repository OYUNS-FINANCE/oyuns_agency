"""Phase-1 graph state and its reducers. See ADR 0002."""

from __future__ import annotations

import operator
from collections.abc import Mapping, Sequence
from typing import Annotated, TypedDict

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.common.brief import IdeaBrief
from app.agents.common.schemas import RunInput
from app.agents.scout.schemas import RawOpportunity
from app.agents.skeptic.schemas import CritiqueScorecard
from app.providers.llm.base import UsageRecord


def merge_by_id(
    left: Sequence[RawOpportunity] | None, right: Sequence[RawOpportunity] | None
) -> list[RawOpportunity]:
    """Append new opportunities; an update with a known id replaces that entry in place."""
    merged = {o.id: o for o in left or []}
    for o in right or []:
        merged[o.id] = o
    return list(merged.values())


def merge_dict[V](left: Mapping[str, V] | None, right: Mapping[str, V] | None) -> dict[str, V]:
    return {**(left or {}), **(right or {})}


class Phase1State(TypedDict, total=False):
    run_id: str
    run_input: RunInput
    iteration: int
    """Number of Scout passes completed."""
    opportunities: Annotated[list[RawOpportunity], merge_by_id]
    analyses: Annotated[dict[str, MarketAnalysis], merge_dict]
    """Keyed by opportunity id."""
    critiques: Annotated[dict[str, CritiqueScorecard], merge_dict]
    """Keyed by opportunity id."""
    composite_scores: dict[str, float]
    """Every scored opportunity, viable or not; replaced on each rank pass."""
    briefs: list[IdeaBrief]
    """Ranked viable ideas (top N); replaced on each rank pass."""
    viable_count: int
    loop_back: bool
    """Rank's routing decision: too few viable ideas and Scout passes remain."""
    shortfall: str | None
    """Honest message when fewer than the minimum viable ideas were found."""
    usage: Annotated[list[UsageRecord], operator.add]
    selected_idea_id: str | None
    phase2: Annotated[dict[str, str], merge_dict]
    """Phase-2 stub markers (node name → status) until Phase 5 replaces the stubs."""
