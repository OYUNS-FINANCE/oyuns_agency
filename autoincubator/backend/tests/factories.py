"""Builders for schema objects and graph deps used across tests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from langgraph.runtime import Runtime

from app.agents.analyst.schemas import MarketAnalysis, MarketAnalysisOutput
from app.agents.common.schemas import RunInput
from app.agents.scout.schemas import RawOpportunity, ScoutCandidate, ScoutQueryPlan
from app.agents.skeptic.schemas import RUBRIC_DIMENSIONS, CritiqueOutput, CritiqueScorecard
from app.core.config import Settings
from app.graph.deps import GraphDeps
from app.providers.dedup import JaccardDeduplicator
from app.providers.llm.fake import FakeLLM, Scripted
from app.providers.search.mock import MockSearchProvider

# URLs that exist in app/providers/search/fixtures/results.json
DENTAL_URL = "https://news.example/2026/dental-phone-confirmations"
HVAC_URL = "https://forum.example/threads/hvac-dispatch-whiteboard"
LANDLORD_URL = "https://appstore.example/reviews/rent-collection"
VET_URL = "https://news.example/2026/vet-staff-shortage"
TUTOR_URL = "https://reviews.example/tutoring-marketplace-commissions"
MARKET_URL = "https://research.example/reports/practice-management-2026"
INJECTION_URL = "https://spam.example/injection-test"


def settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "llm_provider": "fake",
        "quality_threshold": 6.0,
        "max_scout_iterations": 2,
        "min_viable_ideas": 3,
        "max_briefs": 5,
    }
    return Settings(_env_file=None, **{**base, **overrides})


def deps(
    script: Mapping[str, Sequence[Scripted]] | None = None,
    *,
    search: MockSearchProvider | None = None,
    **setting_overrides: Any,
) -> GraphDeps:
    s = settings(**setting_overrides)
    return GraphDeps(
        llm=FakeLLM(script, max_validation_retries=s.llm_max_validation_retries),
        search=search or MockSearchProvider(),
        dedup=JaccardDeduplicator(s.dedup_threshold),
        settings=s,
    )


def runtime(d: GraphDeps) -> Runtime[GraphDeps]:
    return Runtime(context=d)


def seeded_input(**constraints: Any) -> RunInput:
    return RunInput.model_validate(
        {"mode": "seeded", "seed": "small service businesses", "constraints": constraints}
    )


def auto_input() -> RunInput:
    return RunInput(mode="autonomous")


def plan(n_categories: int = 4) -> ScoutQueryPlan:
    cats = ["rising_search", "complaint_thread", "funding_round", "new_regulation",
            "manual_work_job_posting", "marketplace_gap"]  # fmt: skip
    industries = ["healthcare", "trades", "real estate", "education", "fashion", "finance"]
    return ScoutQueryPlan.model_validate(
        {
            "queries": [
                {"category": cats[i], "industry": industries[i], "query": f"{industries[i]} {q}"}
                for i in range(n_categories)
                for q in ("complaints", "manual work")
            ]
        }
    )


def candidate(title: str, url: str = DENTAL_URL, **overrides: Any) -> ScoutCandidate:
    data: dict[str, Any] = {
        "title": title,
        "one_liner": f"{title}: a focused fix for a manual chore",
        "problem": f"Owners lose hours every week because {title.lower()} is manual.",
        "target_customer": f"Owners who need {title.lower()}",
        "industry": "healthcare",
        "business_model": "b2b",
        "signals": [{"category": "complaint_thread", "url": url, "evidence": "Owners complain."}],
        "novelty_score": 7,
        "signal_strength": 7,
        "is_generic": False,
    }
    return ScoutCandidate.model_validate({**data, **overrides})


def opportunity(oid: str, title: str, iteration: int = 1, **overrides: Any) -> RawOpportunity:
    return RawOpportunity(**candidate(title, **overrides).model_dump(), id=oid, iteration=iteration)


def scout_output(*cands: ScoutCandidate) -> dict[str, Any]:
    return {"candidates": [c.model_dump() for c in cands]}


def analysis(source_url: str | None = MARKET_URL) -> MarketAnalysisOutput:
    tam: dict[str, Any] = {"value": 4.1e9, "unit": "USD/year"}
    if source_url:
        tam["source_url"] = source_url
    else:
        tam["assumption"] = "Estimated from clinic counts x average software spend."
    return MarketAnalysisOutput.model_validate(
        {
            "sizing": {
                "method": "top_down",
                "method_explanation": "Sector spend narrowed to independent practices.",
                "tam": tam,
                "sam": {"value": 4.1e8, "unit": "USD/year", "assumption": "10% are independents."},
                "som": {"value": 8.2e6, "unit": "USD/year", "assumption": "2% share in 3 years."},
            },
            "competitors": [
                {
                    "name": "BigSuite",
                    "url": None,
                    "positioning": "Enterprise practice suite.",
                    "price": {"value": 129, "unit": "USD/month", "assumption": "Seat price."},
                }
            ],
            "pricing_benchmarks": [
                {
                    "product": "Point tool",
                    "price": {"value": 49, "unit": "USD/month", "assumption": "Typical SMB tier."},
                    "billing": "monthly",
                }
            ],
            "segments": [{"name": "Independents", "description": "Owner-run clinics."}],
            "summary": "A sizeable, fragmented market served mostly by enterprise suites.",
        }
    )


def critique(score: int | Mapping[str, int] = 7) -> CritiqueOutput:
    scores = score if isinstance(score, Mapping) else dict.fromkeys(RUBRIC_DIMENSIONS, score)
    return CritiqueOutput.model_validate(
        {
            "scores": [
                {"dimension": d, "score": scores[d], "justification": f"Reason for {d}."}
                for d in RUBRIC_DIMENSIONS
            ],
            "most_likely_failure_cause": "Owners stick with the phone because it already works.",
            "attack_summary": "Distribution is the hard part; the product is easy to copy.",
        }
    )


def market_analysis(oid: str, source_url: str | None = MARKET_URL) -> MarketAnalysis:
    return MarketAnalysis(**analysis(source_url).model_dump(), opportunity_id=oid)


def scorecard(oid: str, score: int | Mapping[str, int] = 7) -> CritiqueScorecard:
    return CritiqueScorecard(**critique(score).model_dump(), opportunity_id=oid)
