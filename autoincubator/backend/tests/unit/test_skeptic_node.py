from app.agents.skeptic import prompts
from app.agents.skeptic.node import skeptic_node
from app.agents.skeptic.schemas import RUBRIC_DIMENSIONS
from app.graph.state import Phase1State
from app.providers.llm.fake import FakeLLM
from tests import factories as f


def _state() -> Phase1State:
    return {
        "run_input": f.seeded_input(),
        "opportunities": [
            f.opportunity("opp-01", "Dental reminders"),
            f.opportunity("opp-02", "HVAC dispatch"),
            f.opportunity("opp-03", "Not analysed yet"),
        ],
        "analyses": {"opp-01": f.market_analysis("opp-01"), "opp-02": f.market_analysis("opp-02")},
        "critiques": {"opp-02": f.scorecard("opp-02")},
    }


async def test_critiques_only_analysed_uncritiqued_opportunities() -> None:
    d = f.deps({"skeptic": [f.critique(4)]})
    out = await skeptic_node(_state(), f.runtime(d))
    assert set(out["critiques"]) == {"opp-01"}
    card = out["critiques"]["opp-01"]
    assert sorted(card.score_map()) == sorted(RUBRIC_DIMENSIONS)
    assert card.most_likely_failure_cause
    llm = d.llm
    assert isinstance(llm, FakeLLM)
    assert llm.calls[0].system == prompts.SYSTEM_V1
    assert "Market analysis" in llm.calls[0].messages[0].content


async def test_incomplete_rubric_is_retried() -> None:
    partial = f.critique().model_dump()
    partial["scores"] = partial["scores"][:6]
    d = f.deps({"skeptic": [partial, f.critique(8)]})
    out = await skeptic_node(_state(), f.runtime(d))
    assert out["critiques"]["opp-01"].score_map()["defensibility"] == 8
    assert len(out["usage"]) == 2
