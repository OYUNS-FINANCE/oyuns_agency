from app.agents.analyst.node import analyst_node
from app.agents.common.untrusted import OPEN_TAG
from app.graph.state import Phase1State
from app.providers.llm.fake import FakeLLM
from tests import factories as f


def _state(*titles: str) -> Phase1State:
    return {
        "run_input": f.seeded_input(),
        "opportunities": [f.opportunity(f"opp-{i:02d}", t) for i, t in enumerate(titles, 1)],
    }


async def test_analyses_each_new_opportunity_with_sourced_figures() -> None:
    d = f.deps({"analyst": [f.analysis(), f.analysis(source_url=None)]}, agent_concurrency=1)
    out = await analyst_node(_state("Dental reminders", "HVAC dispatch"), f.runtime(d))
    assert set(out["analyses"]) == {"opp-01", "opp-02"}
    for a in out["analyses"].values():
        assert all(fig.source_url or fig.assumption for fig in a.figures())
    assert out["analyses"]["opp-02"].sizing.tam.is_estimate
    llm = d.llm
    assert isinstance(llm, FakeLLM)
    assert all(OPEN_TAG in c.messages[0].content for c in llm.calls)


async def test_skips_already_analysed_opportunities() -> None:
    d = f.deps({"analyst": [f.analysis()]})
    state = _state("Dental reminders", "HVAC dispatch")
    state["analyses"] = {"opp-01": f.market_analysis("opp-01")}
    out = await analyst_node(state, f.runtime(d))
    assert set(out["analyses"]) == {"opp-02"}


async def test_source_url_must_come_from_search_results() -> None:
    invented = f.analysis(source_url="https://invented.example/report")
    d = f.deps({"analyst": [invented, f.analysis()]})
    out = await analyst_node(_state("Dental reminders"), f.runtime(d))
    llm = d.llm
    assert isinstance(llm, FakeLLM)
    assert "invented.example" in llm.calls[1].messages[-1].content
    assert out["analyses"]["opp-01"].sizing.tam.source_url == f.MARKET_URL


async def test_idea_without_valid_analysis_is_skipped_not_fatal() -> None:
    bad = {"sizing": "nonsense"}
    d = f.deps({"analyst": [bad, bad, bad, f.analysis()]}, agent_concurrency=1)
    out = await analyst_node(_state("Broken idea", "Good idea"), f.runtime(d))
    assert set(out["analyses"]) == {"opp-02"}
    assert len(out["usage"]) == 4
