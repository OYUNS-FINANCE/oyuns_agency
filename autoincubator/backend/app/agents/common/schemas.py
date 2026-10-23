"""Run-level inputs shared by every Phase-1 agent."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator


class FounderProfile(BaseModel):
    skills: list[str] = Field(default_factory=list)
    region: str | None = None
    capital_usd: float | None = Field(default=None, ge=0)
    risk_tolerance: Literal["low", "medium", "high"] = "medium"
    weekly_hours: int | None = Field(default=None, ge=1, le=168)
    rejected_idea_reasons: list[str] = Field(
        default_factory=list,
        description="Reasons from earlier rejections; Mode B steers away from these.",
    )


class RunConstraints(BaseModel):
    region: str | None = None
    budget_ceiling_usd: float | None = Field(default=None, ge=0)
    business_model: Literal["b2b", "b2c", "any"] = "any"
    solo_founder: bool = False
    excluded_industries: list[str] = Field(default_factory=list)


class RunInput(BaseModel):
    mode: Literal["seeded", "autonomous"]
    seed: str | None = Field(default=None, min_length=3, max_length=500)
    constraints: RunConstraints = Field(default_factory=RunConstraints)
    founder_profile: FounderProfile | None = None

    @model_validator(mode="after")
    def _seed_matches_mode(self) -> Self:
        if self.mode == "seeded" and not self.seed:
            raise ValueError("Mode A (seeded) requires a seed")
        if self.mode == "autonomous" and self.seed:
            raise ValueError("Mode B (autonomous) takes no seed")
        return self
