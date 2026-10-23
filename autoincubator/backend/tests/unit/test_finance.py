"""Finance engine against a hand-calculated reference case (tests/factories.assumption_set).

Reference inputs: tiers $20 and $60 at 50/50, payment fee 5%, variable cost $6, churn 5%,
channels paid_search (CAC $100, $1,000/mo) and content_seo (CAC $50, $500/mo), 100 organic
signups growing 10%/mo with 10% free→paid, fixed costs $2,500/mo, cash $20,000, launch month 2.

By hand:
    ARPA = 20*0.5 + 60*0.5 = 40
    var_cost = 6 + 40*0.05 = 8;  GM = 32/40 = 0.8;  contribution = 32
    paid new = 1000/100 + 500/50 = 20;  blended CAC = 1500/20 = 75
    LTV = 32/0.05 = 640;  LTV:CAC = 640/75 = 8.5333…;  payback = 75/32 = 2.34375
    m1 (pre-launch): customers 0, opex 2,500, net -2,500, cash 17,500
    m2: signups 100, new 10+20 = 30, customers 30, MRR 1,200, COGS 240, GP 960,
        opex 2,500+1,500 = 4,000, net -3,040, cash 14,460
    m3: signups 110, new 11+20 = 31, customers 30*0.95+31 = 59.5, MRR 2,380, COGS 476,
        GP 1,904, opex 4,000, net -2,096, cash 12,364
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.agents.financial_modeler.schemas import AssumptionSet
from app.services import finance
from app.services.finance import DEPENDENCIES, FORMULAS, INPUTS, ScenarioResult
from tests import factories as f


def test_unit_economics_match_the_hand_calculation() -> None:
    ue = finance.compute_scenario(f.assumption_set(), "base").unit_economics
    assert ue.arpa == pytest.approx(40)
    assert ue.variable_cost_per_customer == pytest.approx(8)
    assert ue.gross_margin_pct == pytest.approx(0.8)
    assert ue.blended_cac == pytest.approx(75)
    assert ue.ltv == pytest.approx(640)
    assert ue.ltv_to_cac == pytest.approx(640 / 75)
    assert ue.payback_months == pytest.approx(2.34375)


def test_first_three_months_match_the_hand_calculation() -> None:
    m1, m2, m3 = finance.compute_scenario(f.assumption_set(), "base").months[:3]
    assert (m1.signups, m1.new_customers, m1.customers, m1.mrr) == (0, 0, 0, 0)
    assert (m1.opex, m1.net_cash_flow, m1.cash) == (2500, -2500, 17500)
    assert m2.model_dump() == pytest.approx(
        {
            "month": 2,
            "signups": 100,
            "new_customers": 30,
            "customers": 30,
            "mrr": 1200,
            "cogs": 240,
            "gross_profit": 960,
            "opex": 4000,
            "net_cash_flow": -3040,
            "cash": 14460,
        }
    )
    assert m3.model_dump() == pytest.approx(
        {
            "month": 3,
            "signups": 110,
            "new_customers": 31,
            "customers": 59.5,
            "mrr": 2380,
            "cogs": 476,
            "gross_profit": 1904,
            "opex": 4000,
            "net_cash_flow": -2096,
            "cash": 12364,
        }
    )


def test_month_twelve_matches_the_closed_form() -> None:
    """customers_12 = Σ_{j=2..12} new_j * 0.95^(12-j), new_j = 10 * 1.1^(j-2) + 20."""
    result = finance.compute_scenario(f.assumption_set(), "base")

    def customers(t: int) -> float:
        return sum((10 * 1.1 ** (j - 2) + 20) * 0.95 ** (t - j) for j in range(2, t + 1))

    cash_12 = 20000 - 2500 + sum(customers(t) * 32 - 4000 for t in range(2, 13))
    m12 = result.months[-1]
    assert customers(12) == pytest.approx(324.7677373, abs=1e-6)
    assert m12.customers == pytest.approx(customers(12))
    assert m12.mrr == pytest.approx(customers(12) * 40)
    assert m12.net_cash_flow == pytest.approx(customers(12) * 32 - 4000)
    assert m12.cash == pytest.approx(cash_12)
    # Net cash flow turns positive once customers * 32 ≥ 4,000, i.e. at 125 customers.
    first = next(t for t in range(2, 13) if customers(t) * 32 >= 4000)
    assert result.break_even_month == first
    assert result.cash_out_month is None
    assert result.runway_after_m12 is None


def test_bear_and_bull_apply_their_multipliers() -> None:
    model = finance.compute(f.assumption_set())
    assert list(model.scenarios) == ["base", "bear", "bull"]
    bear = model.scenarios["bear"].unit_economics
    assert bear.blended_cac == pytest.approx(97.5)  # 1500 / (1000/130 + 500/65)
    assert bear.ltv == pytest.approx(32 / 0.075)
    assert bear.payback_months == pytest.approx(97.5 / 32)
    bull = model.scenarios["bull"]
    assert bull.unit_economics.blended_cac == pytest.approx(60)
    assert bull.months[1].new_customers == pytest.approx(100 * 0.13 + 1000 / 80 + 500 / 40)
    assert bull.months[2].signups == pytest.approx(100 * 1.15)
    assert model.scenarios["bear"].months[-1].cash < model.base.months[-1].cash
    assert model.base.months[-1].cash < bull.months[-1].cash


def test_scenario_fractions_are_capped_at_one() -> None:
    a = f.assumption_set(free_to_paid=f.assumed(0.9, "share"))
    bull = finance.compute_scenario(a, "bull")
    assert bull.months[1].new_customers == pytest.approx(100 * 1.0 + 1000 / 80 + 500 / 40)


def test_a_burning_business_reports_cash_out_and_runway() -> None:
    a = f.assumption_set(
        starting_cash=f.assumed(5000, "USD"), organic_signups_m1=f.assumed(0, "signups")
    )
    result = finance.compute_scenario(a, "base")
    assert result.cash_out_month == 2  # 5000 - 2500 + (20 * 32 - 4000) < 0
    assert result.months[-1].cash < 0
    assert result.runway_after_m12 is None  # paid customers reach break-even before m12


def test_runway_after_month_twelve_uses_month_twelve_burn() -> None:
    a = f.assumption_set(
        organic_signups_m1=f.assumed(0, "signups"),
        fixed_costs=[{"name": "Team", "monthly": f.assumed(10000, "USD/month")}],
        starting_cash=f.assumed(200000, "USD"),
    )
    result = finance.compute_scenario(a, "base")
    customers_12 = 20 * (1 - 0.95**11) / 0.05  # geometric sum of 20 new per month
    burn_12 = 10000 + 1500 - customers_12 * 32
    last = result.months[-1]
    assert last.net_cash_flow == pytest.approx(-burn_12)
    assert result.break_even_month is None and result.cash_out_month is None
    assert result.runway_after_m12 == pytest.approx(last.cash / burn_12)


def test_without_paid_channels_cac_metrics_are_none() -> None:
    result = finance.compute_scenario(f.assumption_set(channels=[]), "base")
    ue = result.unit_economics
    assert ue.blended_cac is None and ue.ltv_to_cac is None and ue.payback_months is None
    assert result.months[1].new_customers == pytest.approx(10)
    assert result.months[1].opex == 2500


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"monthly_churn": f.assumed(0, "share")}, "monthly_churn must be at least"),
        ({"free_to_paid": f.assumed(1.5, "share")}, "free_to_paid is a fraction"),
        ({"channels": [{"channel": "paid_social", "cac": f.assumed(0, "USD"),
                        "monthly_spend": f.assumed(10, "USD")}]}, "cac must be greater"),
        ({"channels": [{"channel": "paid_search", "cac": f.assumed(1, "USD"),
                        "monthly_spend": f.assumed(1, "USD")},
                       {"channel": "paid_search", "cac": f.assumed(1, "USD"),
                        "monthly_spend": f.assumed(1, "USD")}]}, "may appear only once"),
        ({"price_tiers": [{"name": "Only", "price_monthly": f.assumed(9, "USD"),
                           "mix": f.assumed(0.9, "share")}]}, "mix must sum to 1"),
    ],
)  # fmt: skip
def test_invalid_assumptions_are_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        f.assumption_set(**overrides)


def test_degenerate_economics_raise_a_typed_error() -> None:
    free = [{"name": "Free", "price_monthly": f.assumed(0, "USD"), "mix": f.assumed(1, "share")}]
    with pytest.raises(finance.FinanceInputError, match="ARPA is 0"):
        finance.compute(f.assumption_set(price_tiers=free))
    with pytest.raises(finance.FinanceInputError, match="gross margin"):
        finance.compute(f.assumption_set(variable_cost_per_customer=f.assumed(45, "USD")))


# ---- every dependent number moves, and nothing else does ------------------------------


def _bump(fig: dict[str, Any], factor: float = 1.1) -> dict[str, Any]:
    return {**fig, "value": fig["value"] * factor}


def _perturb(group: str) -> AssumptionSet:
    """The reference case with one input group nudged."""
    d = f.assumption_set().model_dump(mode="json")
    match group:
        case "price_monthly":
            d["price_tiers"][1]["price_monthly"] = _bump(d["price_tiers"][1]["price_monthly"])
        case "mix":
            d["price_tiers"][0]["mix"]["value"] = 0.4
            d["price_tiers"][1]["mix"]["value"] = 0.6
        case "channel_cac":
            d["channels"][0]["cac"] = _bump(d["channels"][0]["cac"])
        case "channel_spend":
            d["channels"][0]["monthly_spend"] = _bump(d["channels"][0]["monthly_spend"])
        case "fixed_costs":
            d["fixed_costs"][0]["monthly"] = _bump(d["fixed_costs"][0]["monthly"])
        case "launch_month":
            d["launch_month"] = 3
        case _:
            d[group] = _bump(d[group])
    return AssumptionSet.model_validate(d)


def _observe(output: str, r: ScenarioResult) -> object:
    """The value of one DEPENDENCIES key in a scenario result."""
    if output.startswith("months."):
        return [getattr(m, output.removeprefix("months.")) for m in r.months]
    if output.startswith("channels."):
        return [getattr(c, output.removeprefix("channels.")) for c in r.channels]
    if output in finance.UnitEconomics.model_fields:
        return getattr(r.unit_economics, output)
    return getattr(r, output)


# Discrete outputs can stay the same under a small nudge; only their non-dependence is exact.
_DISCRETE = {"break_even_month", "cash_out_month", "runway_after_m12"}


def test_every_output_has_dependencies_a_formula_and_an_observer() -> None:
    assert set(DEPENDENCIES) == set(FORMULAS)
    result = finance.compute_scenario(f.assumption_set(), "base")
    for output in DEPENDENCIES:
        _observe(output, result)  # raises AttributeError for an unknown output
    assert all(deps <= set(INPUTS) for deps in DEPENDENCIES.values())
    assert set().union(*DEPENDENCIES.values()) == set(INPUTS)


@pytest.mark.parametrize("group", INPUTS)
def test_changing_one_assumption_updates_exactly_its_dependents(group: str) -> None:
    before = finance.compute_scenario(f.assumption_set(), "base")
    after = finance.compute_scenario(_perturb(group), "base")
    for output in DEPENDENCIES:
        changed = _observe(output, before) != _observe(output, after)
        if group in DEPENDENCIES[output]:
            if output not in _DISCRETE:
                assert changed, f"{output} should change when {group} changes"
        else:
            assert not changed, f"{output} should not depend on {group}"


def test_changing_churn_propagates_through_the_whole_projection() -> None:
    """The acceptance example spelled out: one input, every dependent number."""
    base = finance.compute(f.assumption_set())
    churned = finance.compute(f.assumption_set(monthly_churn=f.assumed(0.10, "share/month")))
    for s in finance.SCENARIO_ORDER:
        a, b = base.scenarios[s], churned.scenarios[s]
        assert b.unit_economics.ltv < a.unit_economics.ltv
        assert b.unit_economics.payback_months == a.unit_economics.payback_months
        assert all(
            x.customers > y.customers for x, y in zip(a.months[2:], b.months[2:], strict=True)
        )
        assert all(x.mrr > y.mrr for x, y in zip(a.months[2:], b.months[2:], strict=True))
        assert all(x.cash > y.cash for x, y in zip(a.months[2:], b.months[2:], strict=True))
        assert [m.opex for m in a.months] == [m.opex for m in b.months]
