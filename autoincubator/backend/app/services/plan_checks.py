"""The Editor's code consistency checks. Failures are listed in the dossier, never hidden.

1. Channel CAC: GTM's channels and Finance's channels match one-to-one, with equal CAC
   (to the cent).
2. MVP scope vs build estimate: the "now" features' estimates (days / 5) are within
   ±20% of the Architect's build estimate (weeks).
3. Launch timing: Finance's launch month is not before the MVP can be built. Calendar
   build weeks = full-time weeks x 40 / the founder's weekly hours (when known);
   earliest launch month = 1 + floor(calendar weeks / (52/12)).
Plus: numbers in the Phase-1 text that trace to nothing (`untraced_number`).
"""

from __future__ import annotations

import math

from app.agents.common.brief import IdeaBrief
from app.agents.common.schemas import CHANNEL_LABELS, RunInput
from app.agents.editor.schemas import ComputedFigure, Contradiction
from app.agents.financial_modeler.schemas import AssumptionSet
from app.agents.gtm_strategist.schemas import GtmPlan
from app.agents.product_architect.schemas import (
    FULL_TIME_HOURS_PER_WEEK,
    WORKING_DAYS_PER_WEEK,
    ProductPlan,
)
from app.services.plan_trace import BRIEF_NON_PROSE, MVP_DAYS_FORMULA, brief_registry
from app.services.trace import iter_strings, untraced_in

MVP_ESTIMATE_TOLERANCE = 0.2
WEEKS_PER_MONTH = 52 / 12


def _money(v: float) -> str:
    return f"${v:,.2f}"


def check_channels(gtm: GtmPlan, a: AssumptionSet) -> list[Contradiction]:
    out: list[Contradiction] = []
    planned = {c.channel: c for c in gtm.channels}
    modelled = {c.channel: c for c in a.channels}
    for kind in planned.keys() - modelled.keys():
        out.append(
            Contradiction(
                code="channel_missing_in_finance",
                origin="check",
                severity="high",
                sections=["gtm", "financials"],
                description=(
                    f"The GTM plan relies on {CHANNEL_LABELS[kind]}, but the financial model "
                    "has no spend or CAC for it."
                ),
                resolution="Add the channel to the financial model, or drop it from the plan.",
            )
        )
    for kind in modelled.keys() - planned.keys():
        out.append(
            Contradiction(
                code="channel_missing_in_gtm",
                origin="check",
                severity="high",
                sections=["gtm", "financials"],
                description=(
                    f"The financial model spends on {CHANNEL_LABELS[kind]}, which the GTM plan "
                    "does not include."
                ),
                resolution="Add the channel to the GTM plan, or remove its spend.",
            )
        )
    for kind in sorted(planned.keys() & modelled.keys()):
        gtm_cac = planned[kind].expected_cac.value
        fin_cac = modelled[kind].cac.value
        if round(gtm_cac, 2) != round(fin_cac, 2):
            out.append(
                Contradiction(
                    code="channel_cac_mismatch",
                    origin="check",
                    severity="high",
                    sections=["gtm", "financials"],
                    description=(
                        f"{CHANNEL_LABELS[kind]}: the GTM plan expects a CAC of "
                        f"{_money(gtm_cac)}, the financial model uses {_money(fin_cac)}."
                    ),
                    resolution="Agree on one CAC; the projections use the financial model's.",
                )
            )
    return out


def check_mvp_estimate(product: ProductPlan) -> list[Contradiction]:
    mvp_weeks = product.mvp_days / WORKING_DAYS_PER_WEEK
    if abs(mvp_weeks / product.build_estimate_weeks - 1) <= MVP_ESTIMATE_TOLERANCE:
        return []
    return [
        Contradiction(
            code="mvp_estimate_mismatch",
            origin="check",
            severity="medium",
            sections=["product"],
            description=(
                f'The "now" features add up to {product.mvp_days:g} days ({mvp_weeks:.1f} '
                f"weeks), but the build estimate is {product.build_estimate_weeks:g} weeks."
            ),
            resolution="Cut the MVP scope or revise the build estimate.",
            figures=[
                ComputedFigure(label="MVP days", value=product.mvp_days, formula=MVP_DAYS_FORMULA),
                ComputedFigure(
                    label="MVP weeks",
                    value=round(mvp_weeks, 1),
                    formula=f"MVP days / {WORKING_DAYS_PER_WEEK}",
                ),
            ],
        )
    ]


def earliest_launch_month(product: ProductPlan, run_input: RunInput) -> tuple[float, int]:
    """(calendar build weeks, earliest month with customers)."""
    profile = run_input.founder_profile
    hours = profile.weekly_hours if profile and profile.weekly_hours else None
    weeks = product.build_estimate_weeks * (FULL_TIME_HOURS_PER_WEEK / hours if hours else 1)
    return weeks, 1 + math.floor(weeks / WEEKS_PER_MONTH)


def check_launch_timing(
    product: ProductPlan, a: AssumptionSet, run_input: RunInput
) -> list[Contradiction]:
    weeks, earliest = earliest_launch_month(product, run_input)
    if a.launch_month >= earliest:
        return []
    return [
        Contradiction(
            code="launch_before_build",
            origin="check",
            severity="high",
            sections=["product", "financials", "launch"],
            description=(
                f"The financial model starts selling in month {a.launch_month}, but the MVP "
                f"takes about {weeks:.1f} calendar weeks to build, so month {earliest} is the "
                "earliest launch."
            ),
            resolution="Move the launch month later, or cut scope so the build fits.",
            figures=[
                ComputedFigure(
                    label="calendar build weeks",
                    value=round(weeks, 1),
                    formula="build weeks x 40 / founder weekly hours",
                ),
                ComputedFigure(
                    label="earliest launch month",
                    value=earliest,
                    formula="1 + floor(calendar weeks / (52/12))",
                ),
            ],
        )
    ]


def check_brief_numbers(brief: IdeaBrief) -> list[Contradiction]:
    untraced = untraced_in(iter_strings(brief, BRIEF_NON_PROSE), brief_registry(brief))
    if not untraced:
        return []
    return [
        Contradiction(
            code="untraced_number",
            origin="check",
            severity="medium",
            sections=["opportunity"],
            description=(
                "The idea brief states numbers that no cited source or stated assumption "
                "supports. Treat them as unverified."
            ),
            untraced=untraced,
        )
    ]


def run_checks(
    brief: IdeaBrief, product: ProductPlan, gtm: GtmPlan, a: AssumptionSet, run_input: RunInput
) -> list[Contradiction]:
    return [
        *check_channels(gtm, a),
        *check_mvp_estimate(product),
        *check_launch_timing(product, a, run_input),
        *check_brief_numbers(brief),
    ]
