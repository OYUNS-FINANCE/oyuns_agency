"""Graph nodes report their work through the EventSink in GraphDeps."""

import asyncio

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver

from app.agents.common.context import gather_bounded
from app.events.schema import AgentCompleted, AgentStarted, AgentThought, AgentToolCall
from app.events.sink import RecordingEventSink
from app.graph.builder import compile_graph
from app.providers.search.mock import MockSearchProvider
from tests import factories as f

IDEAS = [
    ("Dental appointment reminders", f.DENTAL_URL),
    ("HVAC dispatch board", f.HVAC_URL),
    ("Rent collection without fees", f.LANDLORD_URL),
]


async def test_each_agent_emits_started_tool_calls_and_completed() -> None:
    sink = RecordingEventSink()
    search = MockSearchProvider()
    d = f.deps(
        {
            "scout.plan": [f.plan()],
            "scout.extract": [f.scout_output(*(f.candidate(t, u) for t, u in IDEAS))],
            "analyst": [f.analysis(source_url=None) for _ in IDEAS],
            "skeptic": [f.critique(8) for _ in IDEAS],
        },
        search=search,
        events=sink,
        agent_concurrency=1,
    )
    config: RunnableConfig = {"configurable": {"thread_id": "events"}}
    await compile_graph(InMemorySaver()).ainvoke(
        {"run_id": "events", "run_input": f.seeded_input()}, config, context=d
    )

    agents = [a for a, _ in sink.events]
    assert agents[0] == "scout"
    assert [(a, e.node) for a, e in sink.events if isinstance(e, AgentStarted)] == [
        ("scout", "scout"),
        ("analyst", "analyst"),
        ("skeptic", "skeptic"),
    ]
    assert [e.node for e in sink.of_type(AgentCompleted)] == [
        "scout",
        "analyst",
        "skeptic",
        "rank",
    ]
    assert sink.of_type(AgentStarted)[1].items == 3
    completed = {e.node: e.summary for e in sink.of_type(AgentCompleted)}
    assert completed["scout"]["kept"] == 3
    assert completed["analyst"] == {"analysed": 3, "failed": 0, "estimated_figures": 15}
    assert completed["rank"] == {"scored": 3, "viable": 3, "briefs": 3}
    # One tool_call event per search actually run, analyst calls tagged with the idea.
    tool_calls = sink.of_type(AgentToolCall)
    assert [t.query for t in tool_calls] == search.queries
    assert {t.idea_key for t in tool_calls if t.idea_key} == {"opp-01", "opp-02", "opp-03"}
    assert sink.of_type(AgentThought)


async def test_gather_bounded_cancels_siblings_and_reraises_the_first_error() -> None:
    finished: list[int] = []

    async def ok(n: int) -> int:
        await asyncio.sleep(0.05)
        finished.append(n)
        return n

    async def boom() -> int:
        raise LookupError("first")

    with pytest.raises(LookupError, match="first"):
        await gather_bounded([ok(1), boom(), ok(2)], limit=3)
    await asyncio.sleep(0.1)
    assert finished == []
    assert await gather_bounded([ok(1), ok(2)], limit=1) == [1, 2]
