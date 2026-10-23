"""Product Architect I/O schemas: MVP scope, architecture, data model, stack, build estimate."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

FULL_TIME_HOURS_PER_WEEK = 40
WORKING_DAYS_PER_WEEK = 5


class Feature(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=10, max_length=400)
    scope: Literal["now", "later"] = Field(description='"now" = in the MVP.')
    estimate_days: float = Field(
        gt=0, le=120, description="Full-time working days for one developer."
    )


class Component(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    responsibility: str = Field(min_length=10, max_length=300)


class Entity(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    fields: list[str] = Field(min_length=1, max_length=15)
    notes: str | None = Field(default=None, max_length=300)


class StackChoice(BaseModel):
    layer: str = Field(min_length=2, max_length=40, description='e.g. "frontend", "database".')
    choice: str = Field(min_length=2, max_length=80)
    why: str = Field(min_length=10, max_length=300)


class ProductPlan(BaseModel):
    mvp_summary: str = Field(min_length=20, max_length=800)
    features: list[Feature] = Field(min_length=2, max_length=15)
    architecture: str = Field(min_length=20, max_length=1200)
    components: list[Component] = Field(min_length=1, max_length=10)
    data_model: list[Entity] = Field(min_length=1, max_length=12)
    stack: list[StackChoice] = Field(min_length=1, max_length=10)
    build_estimate_weeks: float = Field(
        gt=0, le=52, description="Full-time (40 h) weeks for one developer to ship the MVP."
    )
    build_estimate_basis: str = Field(
        min_length=10, max_length=500, description="How the estimate was derived."
    )

    @model_validator(mode="after")
    def _has_mvp(self) -> Self:
        if not any(f.scope == "now" for f in self.features):
            raise ValueError('at least one feature must have scope "now" (the MVP)')
        return self

    @property
    def mvp_days(self) -> float:
        return sum(f.estimate_days for f in self.features if f.scope == "now")
