"""Financial engine: pure Python, no LLM. The Financial Modeler proposes an AssumptionSet;
this module computes unit economics and a 12-month projection under base/bear/bull.

Formulas (per scenario, after its multipliers are applied):
    ARPA            = Σ price_i * mix_i
    var_cost        = variable_cost_per_customer + ARPA * payment_fee_pct
    GM%             = (ARPA - var_cost) / ARPA
    paid_new_c      = monthly_spend_c / CAC_c
    blended_CAC     = Σ spend_c / Σ paid_new_c          (None without paid acquisition)
    LTV             = ARPA * GM% / churn
    LTV:CAC         = LTV / blended_CAC
    payback_months  = blended_CAC / (ARPA * GM%)
Month t = 1..12, active when t ≥ launch_month, k = t - launch_month:
    signups_t       = organic_signups_m1 * (1 + growth)^k                (0 before launch)
    new_t           = signups_t * free_to_paid + Σ paid_new_c            (0 before launch)
    customers_t     = customers_{t-1} * (1 - churn) + new_t,   customers_0 = 0
    MRR_t           = customers_t * ARPA
    COGS_t          = customers_t * var_cost
    gross_profit_t  = MRR_t - COGS_t
    opex_t          = Σ fixed + Σ spend_c * [active]
    net_cash_flow_t = gross_profit_t - opex_t
    cash_t          = cash_{t-1} + net_cash_flow_t,  cash_0 = starting_cash
    break_even_month = first t with net_cash_flow_t ≥ 0
    cash_out_month   = first t with cash_t < 0
    runway_after_m12 = cash_12 / -net_cash_flow_12 while still burning
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.common.schemas import ChannelType
from app.agents.financial_modeler.schemas import HORIZON_MONTHS, AssumptionSet

ScenarioName = Literal["base", "bear", "bull"]
SCENARIO_ORDER: tuple[ScenarioName, ...] = ("base", "bear", "bull")


class FinanceInputError(ValueError):
    """The assumptions describe a business the engine cannot model (e.g. no revenue)."""


class ScenarioMultipliers(BaseModel):
    """Applied to the base assumptions. Fractions are capped at 1 afterwards."""

    cac: float
    free_to_paid: float
    monthly_churn: float
    organic_growth: float


SCENARIOS: dict[ScenarioName, ScenarioMultipliers] = {
    "base": ScenarioMultipliers(cac=1.0, free_to_paid=1.0, monthly_churn=1.0, organic_growth=1.0),
    "bear": ScenarioMultipliers(cac=1.3, free_to_paid=0.7, monthly_churn=1.5, organic_growth=0.5),
    "bull": ScenarioMultipliers(cac=0.8, free_to_paid=1.3, monthly_churn=0.7, organic_growth=1.5),
}


class UnitEconomics(BaseModel):
    arpa: float
    variable_cost_per_customer: float
    gross_margin_pct: float
    blended_cac: float | None
    ltv: float
    ltv_to_cac: float | None
    payback_months: float | None


class ChannelEconomics(BaseModel):
    channel: ChannelType
    cac: float
    monthly_spend: float
    new_customers_per_month: float


class MonthRow(BaseModel):
    month: int = Field(ge=1, le=HORIZON_MONTHS)
    signups: float
    new_customers: float
    customers: float
    mrr: float
    cogs: float
    gross_profit: float
    opex: float
    net_cash_flow: float
    cash: float


class ScenarioResult(BaseModel):
    scenario: ScenarioName
    multipliers: ScenarioMultipliers
    unit_economics: UnitEconomics
    channels: list[ChannelEconomics]
    months: list[MonthRow] = Field(min_length=HORIZON_MONTHS, max_length=HORIZON_MONTHS)
    break_even_month: int | None
    cash_out_month: int | None
    runway_after_m12: float | None
    """Months of cash left after month 12 at month-12 burn; None when not burning."""


class FinancialModel(BaseModel):
    scenarios: dict[ScenarioName, ScenarioResult]

    @property
    def base(self) -> ScenarioResult:
        return self.scenarios["base"]


# Input groups of an AssumptionSet, and the outputs that depend on each. The appendix
# prints these as "computed from"; tests check them by perturbing every input.
INPUTS = (
    "price_monthly",
    "mix",
    "channel_cac",
    "channel_spend",
    "organic_signups_m1",
    "organic_growth",
    "free_to_paid",
    "monthly_churn",
    "payment_fee_pct",
    "variable_cost_per_customer",
    "fixed_costs",
    "starting_cash",
    "launch_month",
)
_PRICE = frozenset({"price_monthly", "mix"})
_VAR = _PRICE | {"variable_cost_per_customer", "payment_fee_pct"}
_CAC = frozenset({"channel_cac", "channel_spend"})
_NEW = _CAC | {"organic_signups_m1", "organic_growth", "free_to_paid", "launch_month"}
_CUSTOMERS = _NEW | {"monthly_churn"}
_GROSS = _CUSTOMERS | _VAR
_OPEX = frozenset({"fixed_costs", "channel_spend", "launch_month"})
_CASH_FLOW = _GROSS | _OPEX

DEPENDENCIES: dict[str, frozenset[str]] = {
    "arpa": _PRICE,
    "variable_cost_per_customer": _VAR,
    "gross_margin_pct": _VAR,
    "blended_cac": _CAC,
    "ltv": _VAR | {"monthly_churn"},
    "ltv_to_cac": _VAR | {"monthly_churn"} | _CAC,
    "payback_months": _VAR | _CAC,
    "channels.new_customers_per_month": _CAC,
    "months.signups": frozenset({"organic_signups_m1", "organic_growth", "launch_month"}),
    "months.new_customers": _NEW,
    "months.customers": _CUSTOMERS,
    "months.mrr": _CUSTOMERS | _PRICE,
    "months.cogs": _CUSTOMERS | _VAR,
    "months.gross_profit": _GROSS,
    "months.opex": _OPEX,
    "months.net_cash_flow": _CASH_FLOW,
    "months.cash": _CASH_FLOW | {"starting_cash"},
    "break_even_month": _CASH_FLOW,
    "cash_out_month": _CASH_FLOW | {"starting_cash"},
    "runway_after_m12": _CASH_FLOW | {"starting_cash"},
}

FORMULAS: dict[str, str] = {
    "arpa": "Σ tier price * tier mix",
    "variable_cost_per_customer": "variable cost per customer + ARPA * payment fee",
    "gross_margin_pct": "(ARPA - variable cost per customer) / ARPA",
    "blended_cac": "Σ channel spend / Σ (channel spend / channel CAC)",
    "ltv": "ARPA * gross margin / monthly churn",
    "ltv_to_cac": "LTV / blended CAC",
    "payback_months": "blended CAC / (ARPA * gross margin)",
    "channels.new_customers_per_month": "channel spend / channel CAC",
    "months.signups": "organic signups * (1 + organic growth)^(month - launch month)",
    "months.new_customers": "signups * free-to-paid + Σ paid new customers",
    "months.customers": "previous customers * (1 - churn) + new customers",
    "months.mrr": "customers * ARPA",
    "months.cogs": "customers * variable cost per customer",
    "months.gross_profit": "MRR - COGS",
    "months.opex": "Σ fixed costs + Σ channel spend (from launch)",
    "months.net_cash_flow": "gross profit - opex",
    "months.cash": "previous cash + net cash flow",
    "break_even_month": "first month with net cash flow ≥ 0",
    "cash_out_month": "first month with cash < 0",
    "runway_after_m12": "month-12 cash / month-12 burn",
}


@dataclass(frozen=True)
class _Channel:
    name: ChannelType
    cac: float
    spend: float


@dataclass(frozen=True)
class _Inputs:
    """Plain numbers for one scenario, multipliers already applied."""

    prices: tuple[tuple[float, float], ...]
    channels: tuple[_Channel, ...]
    organic_signups_m1: float
    organic_growth: float
    free_to_paid: float
    monthly_churn: float
    payment_fee_pct: float
    variable_cost_per_customer: float
    fixed_costs: float
    starting_cash: float
    launch_month: int


def _inputs(a: AssumptionSet, m: ScenarioMultipliers) -> _Inputs:
    return _Inputs(
        prices=tuple((t.price_monthly.value, t.mix.value) for t in a.price_tiers),
        channels=tuple(
            _Channel(c.channel, c.cac.value * m.cac, c.monthly_spend.value) for c in a.channels
        ),
        organic_signups_m1=a.organic_signups_m1.value,
        organic_growth=min(1.0, a.organic_growth.value * m.organic_growth),
        free_to_paid=min(1.0, a.free_to_paid.value * m.free_to_paid),
        monthly_churn=min(1.0, a.monthly_churn.value * m.monthly_churn),
        payment_fee_pct=a.payment_fee_pct.value,
        variable_cost_per_customer=a.variable_cost_per_customer.value,
        fixed_costs=sum(c.monthly.value for c in a.fixed_costs),
        starting_cash=a.starting_cash.value,
        launch_month=a.launch_month,
    )


def _unit_economics(i: _Inputs) -> UnitEconomics:
    arpa = sum(price * mix for price, mix in i.prices)
    if arpa <= 0:
        raise FinanceInputError("ARPA is 0: at least one paid tier needs a price above 0")
    var_cost = i.variable_cost_per_customer + arpa * i.payment_fee_pct
    gm = (arpa - var_cost) / arpa
    if gm <= 0:
        raise FinanceInputError(
            "gross margin is not positive: variable costs exceed the average price"
        )
    contribution = arpa * gm
    spend = sum(c.spend for c in i.channels)
    paid_new = sum(c.spend / c.cac for c in i.channels)
    blended = spend / paid_new if paid_new > 0 else None
    ltv = contribution / i.monthly_churn
    return UnitEconomics(
        arpa=arpa,
        variable_cost_per_customer=var_cost,
        gross_margin_pct=gm,
        blended_cac=blended,
        ltv=ltv,
        ltv_to_cac=ltv / blended if blended is not None else None,
        payback_months=blended / contribution if blended is not None else None,
    )


def _months(i: _Inputs, ue: UnitEconomics) -> list[MonthRow]:
    paid_new = sum(c.spend / c.cac for c in i.channels)
    spend = sum(c.spend for c in i.channels)
    rows: list[MonthRow] = []
    customers, cash = 0.0, i.starting_cash
    for t in range(1, HORIZON_MONTHS + 1):
        active = t >= i.launch_month
        signups = i.organic_signups_m1 * (1 + i.organic_growth) ** (t - i.launch_month)
        signups = signups if active else 0.0
        new = signups * i.free_to_paid + paid_new if active else 0.0
        customers = customers * (1 - i.monthly_churn) + new
        mrr = customers * ue.arpa
        cogs = customers * ue.variable_cost_per_customer
        gross_profit = mrr - cogs
        opex = i.fixed_costs + (spend if active else 0.0)
        net = gross_profit - opex
        cash += net
        rows.append(
            MonthRow(
                month=t,
                signups=signups,
                new_customers=new,
                customers=customers,
                mrr=mrr,
                cogs=cogs,
                gross_profit=gross_profit,
                opex=opex,
                net_cash_flow=net,
                cash=cash,
            )
        )
    return rows


def compute_scenario(a: AssumptionSet, scenario: ScenarioName) -> ScenarioResult:
    m = SCENARIOS[scenario]
    i = _inputs(a, m)
    ue = _unit_economics(i)
    months = _months(i, ue)
    last = months[-1]
    return ScenarioResult(
        scenario=scenario,
        multipliers=m,
        unit_economics=ue,
        channels=[
            ChannelEconomics(
                channel=c.name,
                cac=c.cac,
                monthly_spend=c.spend,
                new_customers_per_month=c.spend / c.cac,
            )
            for c in i.channels
        ],
        months=months,
        break_even_month=next((r.month for r in months if r.net_cash_flow >= 0), None),
        cash_out_month=next((r.month for r in months if r.cash < 0), None),
        runway_after_m12=(
            max(0.0, last.cash) / -last.net_cash_flow if last.net_cash_flow < 0 else None
        ),
    )


def compute(a: AssumptionSet) -> FinancialModel:
    return FinancialModel(scenarios={s: compute_scenario(a, s) for s in SCENARIO_ORDER})
