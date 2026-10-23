"""Run state machine and leases against Postgres."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.enums import RunStatus
from app.db.models import Run
from app.db.repositories import events as events_repo
from app.db.repositories import runs as runs_repo
from app.db.session import create_engine, create_sessionmaker
from app.services import runs as runs_service
from app.services.schemas import CreateRunRequest
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
        # Leave nothing queued behind: a dev worker's recovery sweep would run it.
        async with sessionmaker() as session, session.begin():
            await session.execute(delete(Run).where(Run.user_id == USER))
        await engine.dispose()


async def _new_run(sm: async_sessionmaker[AsyncSession]) -> uuid.UUID:
    async with sm() as session, session.begin():
        run = await runs_service.create_run(
            session,
            USER,
            CreateRunRequest(mode="seeded", seed="dental clinics"),
            get_settings(),
        )
        return run.id


async def _types(sm: async_sessionmaker[AsyncSession], run_id: uuid.UUID) -> list[str]:
    async with sm() as session:
        return [e.type for e in await events_repo.list_after(session, run_id, 0)]


async def test_refused_transitions_change_nothing_and_emit_nothing(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await _new_run(sm)
    async with sm() as session, session.begin():
        assert not await runs_service.transition(
            session, run_id, USER, RunStatus.AWAITING_HUMAN
        )  # queued → awaiting_human is not allowed
        assert await runs_service.fail(session, run_id, USER, code="x", message="first")
    async with sm() as session, session.begin():
        assert not await runs_service.fail(session, run_id, USER, code="y", message="again")
        assert not await runs_service.transition(session, run_id, USER, RunStatus.RUNNING)

    assert await _types(sm, run_id) == ["run.status", "run.error", "run.status"]
    async with sm() as session:
        run = await runs_repo.get(session, run_id, USER)
        assert run is not None
        assert run.status == RunStatus.FAILED
        assert run.error == {"code": "x", "message": "first"}
        assert run.finished_at is not None


async def test_lease_is_exclusive_until_it_expires(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await _new_run(sm)
    async with sm() as session, session.begin():
        assert await runs_repo.acquire_lease(session, run_id, "worker-a", ttl_s=60)
    async with sm() as session, session.begin():
        assert await runs_repo.acquire_lease(session, run_id, "worker-b", ttl_s=60) is None
        assert await runs_repo.acquire_lease(session, run_id, "worker-a", ttl_s=-1)  # expire it
    async with sm() as session, session.begin():
        assert await runs_repo.acquire_lease(session, run_id, "worker-b", ttl_s=60)
        assert not await runs_repo.renew_lease(session, run_id, "worker-a", ttl_s=60)


async def test_final_transition_requires_the_lease_when_given(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    run_id = await _new_run(sm)
    async with sm() as session, session.begin():
        await runs_repo.acquire_lease(session, run_id, "job-new", ttl_s=60)
        await runs_service.transition(session, run_id, USER, RunStatus.RUNNING)
    async with sm() as session, session.begin():
        assert not await runs_service.fail(
            session, run_id, USER, code="x", message="stale job", lease_owner="job-old"
        )
    assert await _types(sm, run_id) == ["run.status", "run.status"]


async def test_two_jobs_for_one_run_in_one_worker_run_it_once(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    """Regression: the lease belonged to the worker process, so arq's retry of a lost job and
    a recovery job in the same worker both drove the run and one then marked it failed."""
    settings = get_settings()
    engine = create_engine(settings.database_url)
    rt = WorkerRuntime(
        settings=settings.model_copy(update={"fake_llm_latency_ms": 20, "llm_provider": "fake"}),
        engine=engine,
        sessionmaker=create_sessionmaker(engine),
        worker_id="one-worker",
    )
    run_id = await _new_run(sm)
    try:
        outcomes = await asyncio.gather(
            execute_run(rt, run_id, "start:job"), execute_run(rt, run_id, "recover:job")
        )
    finally:
        await engine.dispose()

    assert sorted(outcomes) == ["awaiting_human", "skipped"]
    types = await _types(sm, run_id)
    # queued, running, awaiting_human: a second driver would add another "running".
    assert types.count("run.status") == 3
    assert types[-1] == "run.status" and "run.error" not in types
