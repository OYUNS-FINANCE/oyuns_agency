"""Editor I/O schemas and the assembled BusinessPlan (the dossier's structured form)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.agents.common.brief import IdeaBrief
from app.agents.financial_modeler.schemas import AssumptionSet
from app.agents.gtm_strategist.schemas import GtmPlan
from app.agents.product_architect.schemas import ProductPlan
from app.services.finance import FinancialModel

PlanSection = Literal["opportunity", "product", "gtm", "financials", "launch"]
Severity = Literal["low", "medium", "high"]
ContradictionCode = Literal[
    "channel_cac_mismatch",
    "channel_missing_in_finance",
    "channel_missing_in_gtm",
    "mvp_estimate_mismatch",
    "launch_before_build",
    "untraced_number",
    "editor_review",
]


class ComputedFigure(BaseModel):
    """A number a consistency check derived; listed with its formula in the appendix."""

    label: str
    value: float
    formula: str


class EditorContradiction(BaseModel):
    """A qualitative contradiction the Editor found between sections."""

    sections: list[PlanSection] = Field(min_length=1, max_length=5)
    severity: Severity
    description: str = Field(min_length=10, max_length=500)
    resolution: str = Field(min_length=10, max_length=400)


class Contradiction(BaseModel):
    code: ContradictionCode
    origin: Literal["check", "editor"]
    severity: Severity
    sections: list[PlanSection]
    description: str
    resolution: str | None = None
    figures: list[ComputedFigure] = Field(default_factory=list)
    untraced: list[str] = Field(
        default_factory=list, description="For untraced_number: the numbers as written."
    )


class Risk(BaseModel):
    risk: str = Field(min_length=10, max_length=300)
    mitigation: str = Field(min_length=10, max_length=300)


class LaunchChecklist(BaseModel):
    day_30: list[str] = Field(min_length=2, max_length=8)
    day_60: list[str] = Field(min_length=2, max_length=8)
    day_90: list[str] = Field(min_length=2, max_length=8)


class EditorOutput(BaseModel):
    """What the Editor LLM returns. It cannot change any number."""

    executive_summary: str = Field(min_length=50, max_length=2000)
    contradictions: list[EditorContradiction] = Field(max_length=10)
    risks: list[Risk] = Field(min_length=1, max_length=8)
    checklist: LaunchChecklist


class BusinessPlan(BaseModel):
    idea_id: str = Field(description="Application id (`ideas.id`) of the developed idea.")
    brief: IdeaBrief
    executive_summary: str
    product: ProductPlan
    gtm: GtmPlan
    assumptions: AssumptionSet
    financials: FinancialModel
    contradictions: list[Contradiction]
    risks: list[Risk]
    checklist: LaunchChecklist
