"""Renders a BusinessPlan as the Markdown dossier (templates/dossier.md.j2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from app.agents.analyst.schemas import SourcedFigure
from app.agents.common.schemas import CHANNEL_LABELS
from app.agents.editor.schemas import BusinessPlan
from app.services import finance
from app.services import plan_format as fmt
from app.services.plan_trace import plan_registry
from app.services.trace import FigureRegistry, untraced_in

TEMPLATES = Path(__file__).parent / "templates"

_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    undefined=StrictUndefined,
    autoescape=False,  # Markdown, not HTML; the PDF renderer disables raw HTML
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)
_env.filters.update(
    money=fmt.money,
    pct=fmt.pct,
    num=fmt.num,
    ratio=fmt.ratio,
    month=fmt.month,
    cell=fmt.cell,
    inline=fmt.inline,
    channel=lambda key: CHANNEL_LABELS[key],
    label=lambda key: key.replace("_", " "),
)

_UNIT_ECONOMICS = (
    ("ARPA (per month)", "arpa", fmt.money),
    ("Variable cost per customer", "variable_cost_per_customer", fmt.money),
    ("Gross margin", "gross_margin_pct", fmt.pct),
    ("Blended CAC", "blended_cac", fmt.money),
    ("LTV", "ltv", fmt.money),
    ("LTV:CAC", "ltv_to_cac", fmt.ratio),
    ("Payback (months)", "payback_months", fmt.num),
)


ENGINE_LABELS: dict[str, str] = {
    "arpa": "ARPA",
    "variable_cost_per_customer": "Variable cost per customer",
    "gross_margin_pct": "Gross margin",
    "blended_cac": "Blended CAC",
    "ltv": "LTV",
    "ltv_to_cac": "LTV:CAC",
    "payback_months": "Payback (months)",
    "channels.new_customers_per_month": "New customers per channel",
    "months.signups": "Signups",
    "months.new_customers": "New customers",
    "months.customers": "Customers",
    "months.mrr": "MRR",
    "months.cogs": "COGS",
    "months.gross_profit": "Gross profit",
    "months.opex": "Opex",
    "months.net_cash_flow": "Net cash flow",
    "months.cash": "Cash",
    "break_even_month": "Break-even month",
    "cash_out_month": "Cash-out month",
    "runway_after_m12": "Runway after month 12",
}


@dataclass(frozen=True)
class AssumptionRow:
    section: str
    label: str
    value: str
    basis: str
    """The assumption text, or "Source Sn"."""


@dataclass(frozen=True)
class EngineRow:
    output: str
    formula: str
    inputs: str


def _figure_rows(
    section: str, items: list[tuple[str, SourcedFigure]], sources: dict[str, int]
) -> list[AssumptionRow]:
    rows = []
    for label, f in items:
        if f.source_url is not None:
            basis = f"Source S{sources.setdefault(str(f.source_url), len(sources) + 1)}"
        else:
            basis = f.assumption or ""
        rows.append(AssumptionRow(section, label, fmt.figure(f.value, f.unit), basis))
    return rows


def dossier_context(plan: BusinessPlan, version: int, created: date) -> dict[str, object]:
    brief, a = plan.brief, plan.assumptions
    sources: dict[str, int] = {}
    for s in brief.opportunity.signals:
        sources.setdefault(str(s.url), len(sources) + 1)
    sizing = brief.analysis.sizing
    rows = _figure_rows(
        "Market",
        [("TAM", sizing.tam), ("SAM", sizing.sam), ("SOM", sizing.som)]
        + [(f"{c.name} price", c.price) for c in brief.analysis.competitors if c.price]
        + [(f"{p.product} price", p.price) for p in brief.analysis.pricing_benchmarks]
        + [(f"{s.name} size", s.size) for s in brief.analysis.segments if s.size],
        sources,
    )
    rows += _figure_rows(
        "Go-to-market",
        [(f"{CHANNEL_LABELS[c.channel]} expected CAC", c.expected_cac) for c in plan.gtm.channels],
        sources,
    )
    rows += _figure_rows(
        "Financial model",
        [(f"{t.name} price", t.price_monthly) for t in a.price_tiers]
        + [(f"{t.name} mix", t.mix) for t in a.price_tiers]
        + [(f"{CHANNEL_LABELS[c.channel]} CAC", c.cac) for c in a.channels]
        + [(f"{CHANNEL_LABELS[c.channel]} monthly spend", c.monthly_spend) for c in a.channels]
        + [
            ("Organic signups (launch month)", a.organic_signups_m1),
            ("Organic growth", a.organic_growth),
            ("Free-to-paid conversion", a.free_to_paid),
            ("Monthly churn", a.monthly_churn),
            ("Payment fee", a.payment_fee_pct),
            ("Variable cost per customer", a.variable_cost_per_customer),
            ("Starting cash", a.starting_cash),
        ]
        + [(c.name, c.monthly) for c in a.fixed_costs],
        sources,
    )
    rows.append(
        AssumptionRow(
            "Financial model", "Launch month", f"month {a.launch_month}", a.launch_rationale
        )
    )
    rows.append(
        AssumptionRow(
            "Product",
            "Build estimate",
            f"{plan.product.build_estimate_weeks:g} weeks",
            plan.product.build_estimate_basis,
        )
    )
    engine = [
        EngineRow(
            output=ENGINE_LABELS[key],
            formula=finance.FORMULAS[key],
            inputs=", ".join(sorted(i.replace("_", " ") for i in finance.DEPENDENCIES[key])),
        )
        for key in finance.FORMULAS
    ]
    checks = [f for c in plan.contradictions for f in c.figures]
    return {
        "plan": plan,
        "version": version,
        "created": created.isoformat(),
        "scenarios": [plan.financials.scenarios[s] for s in finance.SCENARIO_ORDER],
        "unit_economics": [
            (
                label,
                [fn(getattr(s.unit_economics, key)) for s in plan.financials.scenarios.values()],
            )
            for label, key, fn in _UNIT_ECONOMICS
        ],
        "mvp": [f for f in plan.product.features if f.scope == "now"],
        "later": [f for f in plan.product.features if f.scope == "later"],
        "sources": sorted(sources.items(), key=lambda kv: kv[1]),
        "assumption_rows": rows,
        "engine_rows": engine,
        "multipliers": [(name, m) for name, m in finance.SCENARIOS.items() if name != "base"],
        "check_figures": checks,
    }


def render_markdown(plan: BusinessPlan, version: int, created: date) -> str:
    return _env.get_template("dossier.md.j2").render(dossier_context(plan, version, created))


def undisclosed_untraced(plan: BusinessPlan, markdown: str) -> list[str]:
    """Numbers in the dossier that trace to nothing and whose value is not disclosed as
    unverified in its contradictions. Empty for a trustworthy dossier (acceptance check)."""
    disclosed = FigureRegistry()
    for c in plan.contradictions:
        disclosed.add_text(" ".join(c.untraced), "brief", "unverified", c.description)
    registry = plan_registry(plan).extend(disclosed)
    return untraced_in([markdown], registry)
