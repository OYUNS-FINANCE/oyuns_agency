"""API-facing request and response models for runs and the founder profile."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.common.schemas import (
    FounderProfile,
    RunConstraints,
    RunInput,
    RunModeName,
    check_seed_for_mode,
)
from app.agents.cowork.schemas import CoworkAgentName
from app.agents.editor.schemas import BusinessPlan
from app.agents.scout.schemas import RawOpportunity
from app.agents.skeptic.schemas import CritiqueScorecard
from app.db.enums import IdeaStatus, IdeaVersionSource, RunStatus
from app.services.brief_patch import PatchOperation


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
    score_stale: bool = Field(
        description="The idea was edited after it was last scored; re-score to update it."
    )
    merged_from: list[uuid.UUID]
    reject_reason: str | None
    title: str
    opportunity: RawOpportunity
    analysis: MarketAnalysis
    critique: CritiqueScorecard


class RunDetail(RunSummary):
    input: RunInput
    shortfall: str | None
    budget: BudgetUsage
    selected_idea_id: uuid.UUID | None
    ideas: list[IdeaView]


# --- Co-working (ADR 0006) -------------------------------------------------------------


class IdeaVersionView(BaseModel):
    version: int
    source: IdeaVersionSource
    created_at: datetime
    composite_score: float
    opportunity: RawOpportunity
    analysis: MarketAnalysis
    critique: CritiqueScorecard
    patch: list[PatchOperation] | None
    message_id: uuid.UUID | None


class IdeaDetail(BaseModel):
    idea: IdeaView
    versions: list[IdeaVersionView]
    """Oldest first."""


class CoworkMessageView(BaseModel):
    id: uuid.UUID
    idea_id: uuid.UUID
    agent: CoworkAgentName
    role: Literal["user", "assistant"]
    state: Literal["pending", "complete", "failed"]
    content: str
    proposed_patch: list[PatchOperation] | None
    based_on_version: int
    applied_version: int | None = Field(description="The version this proposal became, if any.")
    error: str | None
    created_at: datetime


class CoworkMessageList(BaseModel):
    items: list[CoworkMessageView]


class CoworkRequest(BaseModel):
    agent: CoworkAgentName
    content: str = Field(min_length=1, max_length=4000)


class CoworkStarted(BaseModel):
    """First SSE event of a chat reply (`event: started`)."""

    user_message: CoworkMessageView
    assistant_message: CoworkMessageView


class CoworkDelta(BaseModel):
    """`event: delta`: more reply text. `event: reset` (empty object) means discard the text
    so far: the model is retrying after invalid output."""

    text: str


class CoworkFailed(BaseModel):
    """`event: error`; the stored assistant message is marked failed."""

    code: str
    message: str


class ApplyVersionRequest(BaseModel):
    message_id: uuid.UUID


class RejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class MergeRequest(BaseModel):
    idea_ids: list[uuid.UUID] = Field(min_length=2, max_length=4)

    @model_validator(mode="after")
    def _distinct(self) -> Self:
        if len(set(self.idea_ids)) != len(self.idea_ids):
            raise ValueError("idea_ids must be distinct")
        return self


class JobAccepted(BaseModel):
    """Work queued in the worker; progress and the result arrive on the run's stream."""

    job_id: str


class SelectRequest(BaseModel):
    idea_id: uuid.UUID


class SelectResponse(BaseModel):
    run_id: uuid.UUID
    status: RunStatus
    selected_idea_id: uuid.UUID


class ProfileResponse(BaseModel):
    profile: FounderProfile
    updated_at: datetime | None


class EngineFormula(BaseModel):
    key: str
    label: str
    formula: str
    inputs: list[str] = Field(description="Assumption groups this output depends on.")


class PlanResponse(BaseModel):
    run_id: uuid.UUID
    version: int
    created_at: datetime
    plan: BusinessPlan
    engine_formulas: list[EngineFormula]
