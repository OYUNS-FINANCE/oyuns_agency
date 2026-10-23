"""API-facing request and response models for runs and the founder profile."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.common.schemas import (
    FounderProfile,
    RunConstraints,
    RunInput,
    RunModeName,
    check_seed_for_mode,
)
from app.agents.scout.schemas import RawOpportunity
from app.agents.skeptic.schemas import CritiqueScorecard
from app.db.enums import IdeaStatus, IdeaVersionSource, RunStatus


class BudgetRequest(BaseModel):
    """Optional per-run caps. They can only lower the server's limits, never raise them."""

    max_tokens: int | None = Field(default=None, ge=1)
    max_searches: int | None = Field(default=None, ge=1)


class CreateRunRequest(BaseModel):
    mode: RunModeName
    seed: str | None = Field(default=None, min_length=3, max_length=500)
    constraints: RunConstraints = Field(default_factory=RunConstraints)
    budget: BudgetRequest | None = None

    @model_validator(mode="after")
    def _seed_matches_mode(self) -> Self:
        check_seed_for_mode(self.mode, self.seed)
        return self


class CreateRunResponse(BaseModel):
    run_id: uuid.UUID
    status: RunStatus


class RunErrorInfo(BaseModel):
    code: str
    message: str


class BudgetUsage(BaseModel):
    max_tokens: int
    tokens_used: int
    max_searches: int
    searches_used: int
    cost_usd: float


class RunSummary(BaseModel):
    id: uuid.UUID
    mode: RunModeName
    seed: str | None
    status: RunStatus
    error: RunErrorInfo | None
    viable_count: int | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunList(BaseModel):
    items: list[RunSummary]
    total: int
    limit: int
    offset: int


class IdeaView(BaseModel):
    id: uuid.UUID
    key: str
    status: IdeaStatus
    rank: int | None
    composite_score: float | None
    version: int
    version_source: IdeaVersionSource
    title: str
    opportunity: RawOpportunity
    analysis: MarketAnalysis
    critique: CritiqueScorecard


class RunDetail(RunSummary):
    input: RunInput
    shortfall: str | None
    budget: BudgetUsage
    ideas: list[IdeaView]


class ProfileResponse(BaseModel):
    profile: FounderProfile
    updated_at: datetime | None
