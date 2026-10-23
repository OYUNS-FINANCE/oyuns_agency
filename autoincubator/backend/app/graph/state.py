"""Graph state (Phase 1, the checkpoint and Phase 2) and its reducers. See ADR 0002."""

from __future__ import annotations

import operator
from collections.abc import Mapping, Sequence
from typing import Annotated, TypedDict

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.common.brief import IdeaBrief
from app.agents.common.schemas import RunInput
from app.agents.editor.schemas import BusinessPlan
from app.agents.financial_modeler.schemas import AssumptionSet
from app.agents.gtm_strategist.schemas import GtmPlan
from app.agents.product_architect.schemas import ProductPlan
from app.agents.scout.schemas import RawOpportunity
from app.agents.skeptic.schemas import CritiqueScorecard
from app.providers.llm.base import UsageRecord
from app.services.finance import FinancialModel


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
    """Application id (`ideas.id`) of the founder's choice."""
    selected_brief: IdeaBrief | None
    """The selected idea at its latest version; what Phase 2 develops."""
    product: ProductPlan
    gtm: GtmPlan
    assumptions: AssumptionSet
    financials: FinancialModel
    """Computed by the engine from `assumptions`; never by the LLM."""
    plan: BusinessPlan
    """The Editor's assembled plan; the worker persists it as `business_plans` v1."""
