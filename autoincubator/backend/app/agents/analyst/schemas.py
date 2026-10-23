"""Market Analyst I/O schemas. Every number is a SourcedFigure."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from app.core.types import WebUrl


class SourcedFigure(BaseModel):
    """A number that is either backed by a URL or explicitly labelled as an estimate."""

    value: float = Field(ge=0)
    unit: str = Field(min_length=1, max_length=40, description='e.g. "USD", "USD/month", "users".')
    source_url: WebUrl | None = None
    assumption: str | None = Field(
        default=None,
        max_length=500,
        description="Required when there is no source_url: how the estimate was derived.",
    )

    @model_validator(mode="after")
    def _sourced_or_assumed(self) -> Self:
        if self.assumption is not None and not self.assumption.strip():
            self.assumption = None
        if self.source_url is None and self.assumption is None:
            raise ValueError("figure needs a source_url or an explicit assumption")
        return self

    @property
    def is_estimate(self) -> bool:
        return self.source_url is None


class MarketSizing(BaseModel):
    method: Literal["top_down", "bottom_up", "value_theory"]
    method_explanation: str = Field(min_length=10, max_length=800)
    tam: SourcedFigure
    sam: SourcedFigure
    som: SourcedFigure

    @model_validator(mode="after")
    def _nested(self) -> Self:
        if not (self.som.value <= self.sam.value <= self.tam.value):
            raise ValueError("market sizing must satisfy SOM <= SAM <= TAM")
        return self


class Competitor(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    url: WebUrl | None = None
    positioning: str = Field(min_length=3, max_length=400)
    price: SourcedFigure | None = None


class PricingBenchmark(BaseModel):
    product: str = Field(min_length=1, max_length=120)
    price: SourcedFigure
    billing: Literal["one_time", "monthly", "annual", "per_use", "commission"]


class CustomerSegment(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=5, max_length=400)
    size: SourcedFigure | None = None


class MarketAnalysisOutput(BaseModel):
    """What the LLM returns for one opportunity."""

    sizing: MarketSizing
    competitors: list[Competitor] = Field(max_length=8)
    pricing_benchmarks: list[PricingBenchmark] = Field(max_length=8)
    segments: list[CustomerSegment] = Field(min_length=1, max_length=5)
    summary: str = Field(min_length=10, max_length=1000)

    def figures(self) -> list[SourcedFigure]:
        out = [self.sizing.tam, self.sizing.sam, self.sizing.som]
        out += [c.price for c in self.competitors if c.price is not None]
        out += [p.price for p in self.pricing_benchmarks]
        out += [s.size for s in self.segments if s.size is not None]
        return out


class MarketAnalysis(MarketAnalysisOutput):
    opportunity_id: str
