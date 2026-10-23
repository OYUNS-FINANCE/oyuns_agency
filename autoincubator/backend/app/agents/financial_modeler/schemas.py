"""Financial Modeler I/O schemas. The LLM proposes an AssumptionSet; Python computes the rest
(services/finance.py). Every input number is a SourcedFigure: a source URL or a stated
assumption."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, Field, model_validator

from app.agents.analyst.schemas import SourcedFigure
from app.agents.common.schemas import ChannelType

MIX_TOLERANCE = 0.001
MIN_MONTHLY_CHURN = 0.001
HORIZON_MONTHS = 12


class PriceTier(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    price_monthly: SourcedFigure = Field(description="USD per customer per month.")
    mix: SourcedFigure = Field(description="Share of paying customers on this tier, 0 to 1.")


class ChannelAssumption(BaseModel):
    channel: ChannelType = Field(description="Matched against the GTM Strategist's channels.")
    cac: SourcedFigure = Field(description="USD spent per new paying customer; must be > 0.")
    monthly_spend: SourcedFigure = Field(description="USD per month from launch onwards.")


class FixedCost(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    monthly: SourcedFigure = Field(description="USD per month, from month 1.")


class AssumptionSet(BaseModel):
    """What the Financial Modeler returns. No derived numbers: the engine computes those."""

    price_tiers: list[PriceTier] = Field(min_length=1, max_length=4)
    channels: list[ChannelAssumption] = Field(
        max_length=6, description="Paid acquisition channels. Empty = no paid acquisition."
    )
    organic_signups_m1: SourcedFigure = Field(description="Free signups in the launch month.")
    organic_growth: SourcedFigure = Field(description="Monthly growth of free signups, 0 to 1.")
    free_to_paid: SourcedFigure = Field(description="Share of signups that become paying, 0 to 1.")
    monthly_churn: SourcedFigure = Field(description="Share of paying customers lost per month.")
    payment_fee_pct: SourcedFigure = Field(description="Payment processing share of revenue.")
    variable_cost_per_customer: SourcedFigure = Field(
        description="USD per paying customer per month (hosting, support)."
    )
    fixed_costs: list[FixedCost] = Field(max_length=10)
    starting_cash: SourcedFigure = Field(description="USD available at month 0.")
    launch_month: int = Field(
        ge=1, le=HORIZON_MONTHS, description="First month with customers (1 = immediately)."
    )
    launch_rationale: str = Field(min_length=10, max_length=400)

    @model_validator(mode="after")
    def _ranges(self) -> Self:
        mix = sum(t.mix.value for t in self.price_tiers)
        if abs(mix - 1) > MIX_TOLERANCE:
            raise ValueError(f"price tier mix must sum to 1, got {mix:.4f}")
        fractions = {
            "organic_growth": self.organic_growth,
            "free_to_paid": self.free_to_paid,
            "monthly_churn": self.monthly_churn,
            "payment_fee_pct": self.payment_fee_pct,
            **{f"price_tiers[{t.name}].mix": t.mix for t in self.price_tiers},
        }
        for name, fig in fractions.items():
            if fig.value > 1:
                raise ValueError(f"{name} is a fraction between 0 and 1, got {fig.value}")
        if self.monthly_churn.value < MIN_MONTHLY_CHURN:
            raise ValueError(f"monthly_churn must be at least {MIN_MONTHLY_CHURN}")
        for c in self.channels:
            if c.cac.value <= 0:
                raise ValueError(f"channel {c.channel!r}: cac must be greater than 0")
        names = [c.channel for c in self.channels]
        if len(set(names)) != len(names):
            raise ValueError("each channel may appear only once")
        tiers = [t.name.strip().lower() for t in self.price_tiers]
        if len(set(tiers)) != len(tiers):
            raise ValueError("price tier names must be unique")
        return self

    def figures(self) -> list[SourcedFigure]:
        out = [f for t in self.price_tiers for f in (t.price_monthly, t.mix)]
        out += [f for c in self.channels for f in (c.cac, c.monthly_spend)]
        out += [
            self.organic_signups_m1,
            self.organic_growth,
            self.free_to_paid,
            self.monthly_churn,
            self.payment_fee_pct,
            self.variable_cost_per_customer,
            self.starting_cash,
        ]
        out += [c.monthly for c in self.fixed_costs]
        return out
