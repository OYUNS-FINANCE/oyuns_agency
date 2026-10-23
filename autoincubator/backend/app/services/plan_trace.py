"""Figure registries for each part of a business plan (see services/trace.py)."""

from __future__ import annotations

from app.agents.analyst.schemas import SourcedFigure
from app.agents.common.brief import IdeaBrief
from app.agents.editor.schemas import BusinessPlan, Contradiction
from app.agents.financial_modeler.schemas import AssumptionSet
from app.agents.gtm_strategist.schemas import GtmPlan
from app.agents.product_architect.schemas import ProductPlan
from app.services import finance
from app.services.trace import FigureRegistry, iter_strings

MVP_DAYS_FORMULA = 'sum of "now" feature estimates (days)'


def add_figure(r: FigureRegistry, fig: SourcedFigure, label: str) -> None:
    if fig.source_url is not None:
        r.add(fig.value, "source", label, str(fig.source_url))
    else:
        r.add(fig.value, "assumption", label, fig.assumption or "")
    r.add_text(fig.assumption, "assumption", label, fig.assumption or "")


def brief_registry(brief: IdeaBrief) -> FigureRegistry:
    r = FigureRegistry()
    for s in brief.opportunity.signals:
        r.add_text(s.evidence, "source", f"signal: {s.category}", str(s.url))
    a = brief.analysis
    for label, fig in (("TAM", a.sizing.tam), ("SAM", a.sizing.sam), ("SOM", a.sizing.som)):
        add_figure(r, fig, label)
    r.add_text(a.sizing.method_explanation, "assumption", "sizing method", "method_explanation")
    for c in a.competitors:
        if c.price is not None:
            add_figure(r, c.price, f"{c.name} price")
    for p in a.pricing_benchmarks:
        add_figure(r, p.price, f"{p.product} price")
    for seg in a.segments:
        if seg.size is not None:
            add_figure(r, seg.size, f"{seg.name} size")
    r.add(brief.composite_score, "score", "composite score", "weighted rubric mean")
    r.add(brief.opportunity.novelty_score, "score", "novelty", "Scout")
    r.add(brief.opportunity.signal_strength, "score", "signal strength", "Scout")
    for score in brief.critique.scores:
        r.add(score.score, "score", score.dimension, "Skeptic rubric")
    return r


BRIEF_NON_PROSE = frozenset({"id", "url", "source_url"})


def brief_text_registry(brief: IdeaBrief) -> FigureRegistry:
    """Numbers written in the brief's own text. Phase-2 agents may restate them; whether
    they are sourced is the Editor's `untraced_number` check on the brief, not theirs."""
    r = FigureRegistry()
    for text in iter_strings(brief, BRIEF_NON_PROSE):
        r.add_text(text, "brief", "idea brief", "brief text")
    return r


def known_brief_numbers(brief: IdeaBrief) -> FigureRegistry:
    """What a Phase-2 agent may restate from the brief: its figures and its text."""
    return brief_registry(brief).extend(brief_text_registry(brief))


def product_registry(p: ProductPlan) -> FigureRegistry:
    r = FigureRegistry()
    for f in p.features:
        r.add(f.estimate_days, "estimate", f"{f.name} (days)", "Product Architect estimate")
    r.add(p.build_estimate_weeks, "estimate", "build estimate (weeks)", p.build_estimate_basis)
    r.add_text(p.build_estimate_basis, "estimate", "build estimate", p.build_estimate_basis)
    r.add(p.mvp_days, "engine", "MVP days", MVP_DAYS_FORMULA)
    return r


def gtm_registry(g: GtmPlan) -> FigureRegistry:
    r = FigureRegistry()
    for c in g.channels:
        add_figure(r, c.expected_cac, f"{c.channel} expected CAC")
    return r


def assumption_registry(a: AssumptionSet) -> FigureRegistry:
    r = FigureRegistry()
    for t in a.price_tiers:
        add_figure(r, t.price_monthly, f"{t.name} price")
        add_figure(r, t.mix, f"{t.name} mix")
    for c in a.channels:
        add_figure(r, c.cac, f"{c.channel} CAC")
        add_figure(r, c.monthly_spend, f"{c.channel} spend")
    for name in (
        "organic_signups_m1",
        "organic_growth",
        "free_to_paid",
        "monthly_churn",
        "payment_fee_pct",
        "variable_cost_per_customer",
        "starting_cash",
    ):
        add_figure(r, getattr(a, name), name)
    for fc in a.fixed_costs:
        add_figure(r, fc.monthly, fc.name)
    r.add(sum(fc.monthly.value for fc in a.fixed_costs), "engine", "fixed costs", "sum")
    r.add(a.launch_month, "assumption", "launch month", a.launch_rationale)
    r.add_text(a.launch_rationale, "assumption", "launch month", a.launch_rationale)
    return r


def financial_registry(model: finance.FinancialModel) -> FigureRegistry:
    r = FigureRegistry()
    for s in model.scenarios.values():
        for name, value in s.unit_economics.model_dump().items():
            r.add(value, "engine", f"{s.scenario} {name}", finance.FORMULAS[name])
        for name, value in s.multipliers.model_dump().items():
            r.add(value, "engine", f"{s.scenario} {name} multiplier", "scenario definition")
        for c in s.channels:
            r.add(c.cac, "engine", f"{s.scenario} {c.channel} CAC", "CAC x scenario multiplier")
            r.add(
                c.new_customers_per_month,
                "engine",
                f"{s.scenario} {c.channel} new customers",
                finance.FORMULAS["channels.new_customers_per_month"],
            )
        for row in s.months:
            for name, value in row.model_dump(exclude={"month"}).items():
                r.add(value, "engine", f"{s.scenario} m{row.month} {name}", name)
        r.add(s.break_even_month, "engine", "break-even month", "first month net >= 0")
        r.add(s.cash_out_month, "engine", "cash-out month", "first month cash < 0")
        r.add(s.runway_after_m12, "engine", "runway", finance.FORMULAS["runway_after_m12"])
    return r


def contradiction_registry(items: list[Contradiction]) -> FigureRegistry:
    r = FigureRegistry()
    for c in items:
        for f in c.figures:
            r.add(f.value, "engine", f.label, f.formula)
    return r


def plan_registry(plan: BusinessPlan) -> FigureRegistry:
    return (
        brief_registry(plan.brief)
        .extend(product_registry(plan.product))
        .extend(gtm_registry(plan.gtm))
        .extend(assumption_registry(plan.assumptions))
        .extend(financial_registry(plan.financials))
        .extend(contradiction_registry(plan.contradictions))
    )
