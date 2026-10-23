"""Devil's Advocate I/O schemas: a fixed seven-dimension rubric."""

from __future__ import annotations

from typing import Literal, Self, get_args

from pydantic import BaseModel, Field, model_validator

RubricDimension = Literal[
    "cac_risk",
    "channel_dependency",
    "churn_risk",
    "defensibility",
    "regulatory_risk",
    "time_to_first_revenue",
    "solo_founder_feasibility",
]
RUBRIC_DIMENSIONS: tuple[RubricDimension, ...] = get_args(RubricDimension)


class RubricScore(BaseModel):
    """1-10 where 10 is always the favourable end (lowest risk / best outlook)."""

    dimension: RubricDimension
    score: int = Field(ge=1, le=10)
    justification: str = Field(min_length=5, max_length=300, description="One sentence.")


class CritiqueOutput(BaseModel):
    scores: list[RubricScore] = Field(min_length=7, max_length=7)
    most_likely_failure_cause: str = Field(min_length=10, max_length=500)
    attack_summary: str = Field(min_length=10, max_length=1000)

    @model_validator(mode="after")
    def _each_dimension_once(self) -> Self:
        dims = sorted(s.dimension for s in self.scores)
        if dims != sorted(RUBRIC_DIMENSIONS):
            raise ValueError(
                f"scores must cover each rubric dimension exactly once: {RUBRIC_DIMENSIONS}"
            )
        return self

    def score_map(self) -> dict[RubricDimension, int]:
        return {s.dimension: s.score for s in self.scores}


class CritiqueScorecard(CritiqueOutput):
    opportunity_id: str
