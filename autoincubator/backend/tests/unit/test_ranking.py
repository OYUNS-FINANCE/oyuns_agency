import pytest

from app.agents.skeptic.schemas import RUBRIC_DIMENSIONS
from app.core.config import RubricWeights
from app.graph.ranking import composite_score, rank_node
from app.graph.routing import route_after_rank
from app.graph.state import Phase1State
from tests import factories as f


def test_composite_is_weighted_mean() -> None:
    scores: dict[str, int] = {**dict.fromkeys(RUBRIC_DIMENSIONS, 5), "defensibility": 10}
    card = f.scorecard("x", scores)
    equal = RubricWeights(_env_file=None)
    assert composite_score(card, equal) == pytest.approx((5 * 6 + 10) / 7, abs=0.01)
    heavy = RubricWeights(_env_file=None, defensibility=6)
    assert composite_score(card, heavy) == pytest.approx((5 * 6 + 10 * 6) / 12, abs=0.01)


def test_zero_weights_fall_back_to_equal() -> None:
    zero = RubricWeights.model_validate(dict.fromkeys(RUBRIC_DIMENSIONS, 0))
    assert composite_score(f.scorecard("x", 4), zero) == 4.0


def _state(scores: dict[str, int], iteration: int) -> Phase1State:
    ids = list(scores)
    return {
        "run_input": f.seeded_input(),
        "iteration": iteration,
        "opportunities": [f.opportunity(i, f"Idea {i} about {i}") for i in ids],
        "analyses": {i: f.market_analysis(i) for i in ids},
        "critiques": {i: f.scorecard(i, s) for i, s in scores.items()},
    }


async def test_ranks_viable_ideas_and_caps_brief_count() -> None:
    d = f.deps(max_briefs=3)
    scores = {"opp-01": 6, "opp-02": 9, "opp-03": 7, "opp-04": 2, "opp-05": 8}
    out = await rank_node(_state(scores, 1), f.runtime(d))
    assert [b.idea_id for b in out["briefs"]] == ["opp-02", "opp-05", "opp-03"]
    assert [b.rank for b in out["briefs"]] == [1, 2, 3]
    assert out["viable_count"] == 4
    assert out["composite_scores"]["opp-04"] == 2.0
    assert out["loop_back"] is False and out["shortfall"] is None
    assert route_after_rank(out) == "checkpoint"


async def test_too_few_viable_loops_back_while_passes_remain() -> None:
    out = await rank_node(_state({"opp-01": 9, "opp-02": 3}, 1), f.runtime(f.deps()))
    assert out["loop_back"] is True and out["shortfall"] is None
    assert route_after_rank(out) == "scout"


async def test_too_few_viable_after_last_pass_reports_shortfall() -> None:
    out = await rank_node(_state({"opp-01": 9, "opp-02": 3}, 2), f.runtime(f.deps()))
    assert out["loop_back"] is False
    assert out["shortfall"] is not None and "Only 1 idea(s)" in out["shortfall"]
    assert [b.idea_id for b in out["briefs"]] == ["opp-01", "opp-02"]
    assert [b.below_threshold for b in out["briefs"]] == [False, True]
    assert out["viable_count"] == 1
    assert route_after_rank(out) == "checkpoint"


async def test_nothing_viable_still_shows_best_below_threshold() -> None:
    out = await rank_node(
        _state({"opp-01": 2, "opp-02": 4, "opp-03": 3, "opp-04": 1}, 2), f.runtime(f.deps())
    )
    assert [b.idea_id for b in out["briefs"]] == ["opp-02", "opp-03", "opp-01"]
    assert all(b.below_threshold for b in out["briefs"])
    assert out["viable_count"] == 0
