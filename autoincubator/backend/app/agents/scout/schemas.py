"""Trend Scout I/O schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.types import WebUrl

SignalCategory = Literal[
    "rising_search",
    "funding_round",
    "new_regulation",
    "complaint_thread",
    "manual_work_job_posting",
    "marketplace_gap",
    "seed_research",
]
SIGNAL_CATEGORIES: tuple[SignalCategory, ...] = (
    "rising_search",
    "funding_round",
    "new_regulation",
    "complaint_thread",
    "manual_work_job_posting",
    "marketplace_gap",
)


class SignalQuery(BaseModel):
    category: SignalCategory
    industry: str = Field(min_length=2, max_length=80)
    query: str = Field(min_length=3, max_length=200)


class ScoutQueryPlan(BaseModel):
    """LLM step 1: what to search for."""

    queries: list[SignalQuery] = Field(min_length=1, max_length=18)


class SignalSource(BaseModel):
    category: SignalCategory
    url: WebUrl
    evidence: str = Field(min_length=3, max_length=400, description="What this source shows.")


class ScoutCandidate(BaseModel):
    """LLM step 2: one raw idea, before the node assigns an id."""

    title: str = Field(min_length=3, max_length=120)
    one_liner: str = Field(min_length=10, max_length=300)
    problem: str = Field(min_length=10, max_length=800)
    target_customer: str = Field(min_length=3, max_length=300)
    industry: str = Field(min_length=2, max_length=80)
    business_model: Literal["b2b", "b2c", "b2b2c"]
    signals: list[SignalSource] = Field(min_length=1, max_length=6)
    novelty_score: int = Field(ge=1, le=10, description="10 = clearly not already crowded.")
    signal_strength: int = Field(
        ge=1, le=10, description="10 = several independent, specific signals; 1 = generic idea."
    )
    is_generic: bool = Field(
        description='True for undifferentiated ideas such as "AI chatbot for X".'
    )


class ScoutOutput(BaseModel):
    candidates: list[ScoutCandidate] = Field(max_length=15)


class RawOpportunity(ScoutCandidate):
    id: str = Field(min_length=1)
    iteration: int = Field(ge=1, description="Scout pass that produced this opportunity.")
