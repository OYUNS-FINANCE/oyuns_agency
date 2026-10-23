"""GTM Strategist I/O schemas. Channels use the shared vocabulary so Finance can match them."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.agents.analyst.schemas import SourcedFigure
from app.agents.common.schemas import ChannelType


class IdealCustomerProfile(BaseModel):
    description: str = Field(min_length=10, max_length=500)
    attributes: list[str] = Field(min_length=1, max_length=8, description="Who exactly.")
    pains: list[str] = Field(min_length=1, max_length=6)
    buying_trigger: str = Field(min_length=5, max_length=300)


class GtmChannel(BaseModel):
    channel: ChannelType
    rationale: str = Field(min_length=10, max_length=400)
    expected_cac: SourcedFigure = Field(description="USD per new paying customer.")


class Tactic(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=10, max_length=400)


class LaunchStep(BaseModel):
    step: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=10, max_length=400)


class GtmPlan(BaseModel):
    positioning: str = Field(min_length=20, max_length=600)
    icp: IdealCustomerProfile
    channels: list[GtmChannel] = Field(
        min_length=1, max_length=6, description="Paid channels, cheapest expected CAC first."
    )
    zero_budget_tactics: list[Tactic] = Field(min_length=1, max_length=6)
    viral_loops: list[Tactic] = Field(max_length=4)
    first_100_customers: list[LaunchStep] = Field(min_length=2, max_length=8)

    @model_validator(mode="after")
    def _ranked_and_unique(self) -> Self:
        kinds = [c.channel for c in self.channels]
        if len(set(kinds)) != len(kinds):
            raise ValueError("each channel may appear only once")
        cacs = [c.expected_cac.value for c in self.channels]
        if cacs != sorted(cacs):
            raise ValueError("channels must be ranked by expected_cac, cheapest first")
        for c in self.channels:
            if c.expected_cac.value <= 0:
                raise ValueError(f"channel {c.channel}: expected_cac must be greater than 0")
        return self
