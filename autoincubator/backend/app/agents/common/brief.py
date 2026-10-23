"""The ranked, founder-facing output of Phase 1."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.scout.schemas import RawOpportunity
from app.agents.skeptic.schemas import CritiqueScorecard


class IdeaBrief(BaseModel):
    rank: int = Field(ge=1)
    composite_score: float = Field(ge=1, le=10)
    opportunity: RawOpportunity
    analysis: MarketAnalysis
    critique: CritiqueScorecard

    @property
    def idea_id(self) -> str:
        return self.opportunity.id


class CheckpointPayload(BaseModel):
    """The value passed to interrupt(): what the founder sees while the run is paused."""

    briefs: list[IdeaBrief]
    viable_count: int
    shortfall: str | None
    iterations: int
    error: str | None = None
    """Set when the previous resume value was rejected; the founder must choose again."""


class ResumePayload(BaseModel):
    """The value expected in Command(resume=...)."""

    selected_idea_id: str = Field(min_length=1)
