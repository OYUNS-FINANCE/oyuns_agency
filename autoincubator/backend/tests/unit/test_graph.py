"""Whole-graph behaviour on the in-memory saver (allowed in unit tests only)."""

from typing import Any

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.agents.common.brief import CheckpointPayload, ResumePayload
from app.graph.builder import IncubatorGraph, compile_graph
from app.graph.deps import GraphDeps
from app.graph.state import Phase1State
from app.graph.stubs import PHASE2_EDITOR, PHASE2_PARALLEL, STUB_STATUS
from app.providers.llm.fake import FakeLLM
from tests import factories as f

CONFIG: RunnableConfig = {"configurable": {"thread_id": "t-1"}}

GOOD = [
    ("Dental appointment reminders", f.DENTAL_URL),
    ("HVAC dispatch board", f.HVAC_URL),
    ("Rent collection without fees", f.LANDLORD_URL),
    ("Vet clinic admin assistant", f.VET_URL),
]


def _graph() -> IncubatorGraph:
    return compile_graph(InMemorySaver())


def _initial() -> Phase1State:
    return {"run_id": "t-1", "run_input": f.seeded_input()}


def _script(ideas: list[tuple[str, str]], critique_scores: list[int]) -> dict[str, list[Any]]:
    return {
        "scout.plan": [f.plan()],
        "scout.extract": [f.scout_output(*(f.candidate(t, u) for t, u in ideas))],
        "analyst": [f.analysis(source_url=None) for _ in ideas],
        "skeptic": [f.critique(s) for s in critique_scores],
    }


def _select(payload: CheckpointPayload, key: str) -> dict[str, Any]:
    brief = next(b for b in payload.briefs if b.idea_id == key)
    return ResumePayload(idea_id=f"uuid-{key}", brief=brief).model_dump(mode="json")


def _payload(result: dict[str, Any]) -> CheckpointPayload:
    (intr,) = result["__interrupt__"]
    return CheckpointPayload.model_validate(intr.value)


async def test_runs_to_interrupt_with_ranked_briefs_then_resumes_to_phase2_stubs() -> None:
    d = f.deps(_script(GOOD, [8, 7, 9, 3]), agent_concurrency=1)
    graph = _graph()
    result = await graph.ainvoke(_initial(), CONFIG, context=d)

    payload = _payload(result)
    assert [b.idea_id for b in payload.briefs] == ["opp-03", "opp-01", "opp-02"]
    assert [b.composite_score for b in payload.briefs] == [9.0, 8.0, 7.0]
    assert payload.viable_count == 3 and payload.shortfall is None and payload.iterations == 1
    snapshot = await graph.aget_state(CONFIG)
    assert snapshot.next == ("checkpoint",)
    assert not snapshot.values.get("phase2")

    final = await graph.ainvoke(Command(resume=_select(payload, "opp-01")), CONFIG, context=d)
    assert final["selected_idea_id"] == "uuid-opp-01"
    assert final["selected_brief"] == payload.briefs[1]
    assert final["phase2"] == dict.fromkeys((*PHASE2_PARALLEL, PHASE2_EDITOR), STUB_STATUS)
    assert (await graph.aget_state(CONFIG)).next == ()
    assert len(final["usage"]) == 2 + 4 + 4


async def test_quality_loop_runs_exactly_once_then_reports_shortfall_honestly() -> None:
    first = GOOD[:2]
    second = [("Tutoring without commissions", f.TUTOR_URL)]
    d: GraphDeps = f.deps(
        {
            "scout.plan": [f.plan(), f.plan()],
            "scout.extract": [
                f.scout_output(*(f.candidate(t, u) for t, u in first)),
                f.scout_output(*(f.candidate(t, u) for t, u in second)),
            ],
            "analyst": [f.analysis(source_url=None) for _ in range(3)],
            "skeptic": [f.critique(9), f.critique(2), f.critique(3)],
        },
        agent_concurrency=1,
    )
    result = await _graph().ainvoke(_initial(), CONFIG, context=d)

    payload = _payload(result)
    assert payload.iterations == 2  # one loop back, no more
    assert payload.viable_count == 1
    assert [b.idea_id for b in payload.briefs] == ["opp-01"]  # not padded with failures
    assert payload.shortfall is not None
    assert "fewer than the 3 requested" in payload.shortfall
    llm = d.llm
    assert isinstance(llm, FakeLLM)
    assert sum(c.agent == "scout.plan" for c in llm.calls) == 2
    assert all(llm.remaining(a) == 0 for a in ("scout.extract", "analyst", "skeptic"))
    # The second pass analysed and critiqued only the new idea.
    assert sum(c.agent == "analyst" for c in llm.calls) == 3


async def test_enough_ideas_on_first_pass_does_not_loop() -> None:
    d = f.deps(_script(GOOD[:3], [7, 7, 7]), agent_concurrency=1)
    result = await _graph().ainvoke(_initial(), CONFIG, context=d)
    assert _payload(result).iterations == 1


async def test_resume_accepts_an_edited_brief_that_is_not_in_the_snapshot() -> None:
    d = f.deps(_script(GOOD[:3], [7, 7, 7]), agent_concurrency=1)
    graph = _graph()
    payload = _payload(await graph.ainvoke(_initial(), CONFIG, context=d))
    edited = payload.briefs[0].model_copy(deep=True)
    edited.opportunity.title = "Edited during co-working"
    resume = ResumePayload(idea_id="merged-or-edited", brief=edited).model_dump(mode="json")
    final = await graph.ainvoke(Command(resume=resume), CONFIG, context=d)
    assert final["selected_brief"].opportunity.title == "Edited during co-working"
    assert final["phase2"] == dict.fromkeys((*PHASE2_PARALLEL, PHASE2_EDITOR), STUB_STATUS)


@pytest.mark.parametrize(
    "bad", [{"selected_idea_id": "opp-01"}, {"idea_id": "x", "brief": {}}, "opp-01"]
)
async def test_invalid_selection_re_asks_and_run_stays_paused(bad: Any) -> None:
    d = f.deps(_script(GOOD[:3], [7, 7, 7]), agent_concurrency=1)
    graph = _graph()
    await graph.ainvoke(_initial(), CONFIG, context=d)
    again = await graph.ainvoke(Command(resume=bad), CONFIG, context=d)
    payload = _payload(again)
    assert payload.error is not None
    assert [b.idea_id for b in payload.briefs] == ["opp-01", "opp-02", "opp-03"]
    assert (await graph.aget_state(CONFIG)).next == ("checkpoint",)
    final = await graph.ainvoke(Command(resume=_select(payload, "opp-02")), CONFIG, context=d)
    assert final["selected_brief"].idea_id == "opp-02"


async def test_offline_responder_runs_both_modes_end_to_end() -> None:
    from app.providers.factory import build_deps

    for run_input in (f.seeded_input(), f.auto_input()):
        d = build_deps(f.settings())
        graph = _graph()
        cfg: RunnableConfig = {"configurable": {"thread_id": run_input.mode}}
        result = await graph.ainvoke({"run_input": run_input}, cfg, context=d)
        payload = _payload(result)
        assert payload.briefs or payload.shortfall
        for brief in payload.briefs:
            assert all(fig.source_url or fig.assumption for fig in brief.analysis.figures())
