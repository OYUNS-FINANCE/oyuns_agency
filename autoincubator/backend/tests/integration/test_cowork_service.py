"""Co-working services against Postgres, with the worker driven in-process (ADR 0006)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from langgraph.runtime import Runtime
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.common.schemas import RunInput
from app.agents.scout.node import scout_node
from app.core.config import get_settings
from app.core.errors import ConflictError
from app.db.enums import IdeaStatus, RunStatus
from app.db.models import FounderProfileRow, Run
from app.db.repositories import events as events_repo
from app.db.repositories import ideas as ideas_repo
from app.db.repositories import runs as runs_repo
from app.db.session import create_engine, create_sessionmaker
from app.graph.builder import compile_graph
from app.graph.checkpointer import postgres_checkpointer
from app.graph.deps import GraphDeps
from app.providers.dedup import JaccardDeduplicator
from app.providers.llm.fake import FakeLLM, offline_responder
from app.providers.search.mock import MockSearchProvider
from app.services import cowork as cowork_service
from app.services import runs as runs_service
from app.services.cowork_chat import ChatTasks, start_chat
from app.services.schemas import CoworkRequest, CreateRunRequest
from app.worker.runs import WorkerRuntime, execute_run

pytestmark = pytest.mark.integration

USER = uuid.uuid4()


@pytest.fixture
async def sm() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(get_settings().database_url)
    sessionmaker = create_sessionmaker(engine)
    try:
        yield sessionmaker
    finally:
        async with sessionmaker() as session, session.begin():
            await session.execute(delete(Run).where(Run.user_id == USER))
            await session.execute(
                delete(FounderProfileRow).where(FounderProfileRow.user_id == USER)
            )
        await engine.dispose()


@pytest.fixture
async def rt() -> AsyncIterator[WorkerRuntime]:
    settings = get_settings().model_copy(update={"llm_provider": "fake", "fake_llm_latency_ms": 0})
    engine = create_engine(settings.database_url)
    try:
        yield WorkerRuntime(
            settings=settings,
            engine=engine,
            sessionmaker=create_sessionmaker(engine),
            worker_id="test-worker",
        )
    finally:
        await engine.dispose()


async def _paused_run(
    sm: async_sessionmaker[AsyncSession], rt: WorkerRuntime, **request: object
) -> uuid.UUID:
    body = CreateRunRequest.model_validate({"mode": "seeded", "seed": "dental clinics", **request})
    async with sm() as session, session.begin():
        run = await runs_service.create_run(session, USER, body, get_settings())
    assert await execute_run(rt, run.id, f"start:{run.id}") == "awaiting_human"
    return run.id


async def _ideas(sm: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> list[uuid.UUID]:
    async with sm() as session:
        return [idea.id for idea, _ in await ideas_repo.latest_for_run(session, run_id)]


async def _types(sm: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> list[str]:
    async with sm() as session:
        return [e.type for e in await events_repo.list_after(session, run_id, 0)]


async def test_double_select_resumes_exactly_once(
    sm: async_sessionmaker[AsyncSession], rt: WorkerRuntime
) -> None:
    run_id = await _paused_run(sm, rt)
    chosen, other, *_ = await _ideas(sm, run_id)

    async def select() -> bool:
        async with sm() as session, session.begin():
            _, resumed = await cowork_service.select(session, USER, run_id, chosen)
            return resumed

    # Five "clicks" at once: the run lock lets exactly one resume.
    assert sorted(await asyncio.gather(*(select() for _ in range(5)))) == [False] * 4 + [True]
    # A different idea after the resume is a conflict; the same one stays idempotent.
    async with sm() as session, session.begin():
        with pytest.raises(ConflictError, match="cannot be resumed"):
            await cowork_service.select(session, USER, run_id, other)
    assert not await select()

    # The resume job and a recovery job race for the run: one drives it, once.
    outcomes = await asyncio.gather(
        execute_run(rt, run_id, f"resume:{run_id}"), execute_run(rt, run_id, "recover:x")
    )
    assert sorted(outcomes) == ["completed", "skipped"]

    types = await _types(sm, run_id)
    assert types.count("run.resumed") == 1 and types.count("run.completed") == 1
    async with sm() as session:
        statuses = [
            (e.data.previous, e.data.status)
            for e in await events_repo.list_after(session, run_id, 0)
            if e.type == "run.status"
        ]
        run = await runs_repo.get(session, run_id, USER)
        idea = await ideas_repo.get(session, run_id, chosen)
    assert statuses.count((RunStatus.AWAITING_HUMAN, RunStatus.RUNNING)) == 1
    assert statuses[-1] == (RunStatus.RUNNING, RunStatus.COMPLETED)
    assert "Recovered" not in str(types)
    assert run is not None and run.status == RunStatus.COMPLETED
    assert run.selected_idea_id == chosen
    assert idea is not None and idea.status == IdeaStatus.SELECTED

    # The graph got the brief from the DB and ran Phase 2 to the end.
    async with postgres_checkpointer(rt.settings) as saver:
        snapshot = await compile_graph(saver).aget_state(
            {"configurable": {"thread_id": str(run_id)}}
        )
    assert snapshot.next == ()
    assert snapshot.values["selected_idea_id"] == str(chosen)
    assert snapshot.values["selected_brief"].opportunity.title
    assert set(snapshot.values["phase2"]) == {
        "product_architect",
        "gtm_strategist",
        "financial_modeler",
        "editor",
    }


async def test_edited_idea_is_what_the_graph_resumes_with(
    sm: async_sessionmaker[AsyncSession], rt: WorkerRuntime
) -> None:
    run_id = await _paused_run(sm, rt)
    chosen = (await _ideas(sm, run_id))[0]
    tasks = ChatTasks()
    stream = await start_chat(
        sm,
        rt.settings,
        tasks,
        USER,
        run_id,
        chosen,
        CoworkRequest(agent="scout", content="EU only"),
    )
    events = [name async for name, _ in stream]
    assert events[0] == "started" and events[-1] == "completed" and "delta" in events
    async with sm() as session:
        messages = await cowork_service.list_messages(session, USER, run_id, chosen, rt.settings)
    reply = messages.items[1]
    assert reply.state == "complete" and reply.proposed_patch
    async with sm() as session, session.begin():
        view, created = await cowork_service.apply_version(session, USER, run_id, chosen, reply.id)
    assert created and view.version == 2 and view.score_stale
    assert "EU only" in view.opportunity.one_liner

    async with sm() as session, session.begin():
        await cowork_service.select(session, USER, run_id, chosen)
    assert await execute_run(rt, run_id, f"resume:{run_id}") == "completed"
    async with postgres_checkpointer(rt.settings) as saver:
        snapshot = await compile_graph(saver).aget_state(
            {"configurable": {"thread_id": str(run_id)}}
        )
    assert snapshot.values["selected_brief"].opportunity.one_liner == view.opportunity.one_liner


async def test_rejected_reasons_reach_the_next_mode_b_scout(
    sm: async_sessionmaker[AsyncSession], rt: WorkerRuntime
) -> None:
    run_id = await _paused_run(sm, rt)
    first, second, *_ = await _ideas(sm, run_id)
    async with sm() as session, session.begin():
        view = await cowork_service.reject(
            session, USER, run_id, first, "needs a field sales team", rt.settings
        )
        await cowork_service.reject(session, USER, run_id, second, None, rt.settings)
    assert view.status == IdeaStatus.REJECTED and view.rank is None
    assert view.reject_reason == "needs a field sales team"

    async with sm() as session, session.begin():
        auto = await runs_service.create_run(
            session, USER, CreateRunRequest(mode="autonomous"), get_settings()
        )
    run_input = RunInput.model_validate(auto.input)
    assert run_input.founder_profile is not None
    assert run_input.founder_profile.rejected_idea_reasons == [
        f"{view.title}: needs a field sales team"  # the reason-less rejection is not kept
    ]

    llm = FakeLLM(responder=offline_responder)
    deps = GraphDeps(
        llm=llm,
        search=MockSearchProvider(),
        dedup=JaccardDeduplicator(0.6),
        settings=rt.settings,
    )
    await scout_node({"run_id": str(auto.id), "run_input": run_input}, Runtime(context=deps))
    plan_prompt = next(c for c in llm.calls if c.agent == "scout.plan").messages[0].content
    assert "reasons earlier ideas were rejected" in plan_prompt
    assert f"{view.title}: needs a field sales team" in plan_prompt


async def test_cowork_writes_are_refused_unless_the_run_is_paused(
    sm: async_sessionmaker[AsyncSession], rt: WorkerRuntime
) -> None:
    run_id = await _paused_run(sm, rt)
    idea = (await _ideas(sm, run_id))[0]
    async with sm() as session, session.begin():
        await runs_service.transition(session, run_id, USER, RunStatus.RUNNING)

    calls: dict[str, Callable[[AsyncSession], Awaitable[object]]] = {
        "apply": lambda s: cowork_service.apply_version(s, USER, run_id, idea, uuid.uuid4()),
        "reject": lambda s: cowork_service.reject(s, USER, run_id, idea, "x", rt.settings),
        "rescore": lambda s: cowork_service.check_rescore(s, USER, run_id, idea),
        "merge": lambda s: cowork_service.check_merge(s, USER, run_id, [idea, uuid.uuid4()]),
    }
    for name, call in calls.items():
        async with sm() as session, session.begin():
            with pytest.raises(ConflictError) as info:
                await call(session)
        assert info.value.code == "run_not_paused", name
    with pytest.raises(ConflictError) as info:
        await start_chat(
            sm,
            rt.settings,
            ChatTasks(),
            USER,
            run_id,
            idea,
            CoworkRequest(agent="scout", content="hi"),
        )
    assert info.value.code == "run_not_paused"


async def test_exhausted_budget_refuses_cowork_but_keeps_the_run_paused(
    sm: async_sessionmaker[AsyncSession], rt: WorkerRuntime
) -> None:
    run_id = await _paused_run(sm, rt)
    idea = (await _ideas(sm, run_id))[0]
    async with sm() as session, session.begin():
        run = await runs_repo.get_for_update(session, run_id, USER)
        assert run is not None
        run.max_tokens = run.tokens_used
    async with sm() as session, session.begin():
        with pytest.raises(ConflictError) as info:
            await cowork_service.check_rescore(session, USER, run_id, idea)
    assert info.value.code == "budget_exhausted"
    async with sm() as session, session.begin():
        _, resumed = await cowork_service.select(session, USER, run_id, idea)
    assert resumed
