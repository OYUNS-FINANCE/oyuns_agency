"""Run execution in the worker: lease → graph to the interrupt → persist ideas. ADR 0004."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.agents.common.brief import CheckpointPayload
from app.agents.common.schemas import RunInput
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.enums import RunStatus
from app.db.models import Run
from app.db.repositories import events as events_repo
from app.db.repositories import ideas as ideas_repo
from app.db.repositories import runs as runs_repo
from app.db.repositories.search_cache import PostgresSearchCache
from app.events.publisher import PostgresEventSink
from app.events.schema import (
    EventData,
    IdeaCreated,
    RunCompleted,
    RunInterrupted,
    RunStatusChanged,
)
from app.graph.builder import compile_graph
from app.graph.checkpointer import postgres_checkpointer
from app.graph.state import Phase1State
from app.providers.factory import build_deps
from app.providers.llm.base import UsageRecord
from app.services import runs as runs_service
from app.services.budget import BudgetExhaustedError, RunBudget
from app.services.runs import START_RUN

log = get_logger(__name__)


class LeaseLostError(RuntimeError):
    def __init__(self, run_id: uuid.UUID):
        super().__init__(f"lease on run {run_id} was taken over by another job")


@dataclass(frozen=True)
class WorkerRuntime:
    settings: Settings
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    worker_id: str


class PostgresUsageStore:
    def __init__(self, rt: WorkerRuntime, run_id: uuid.UUID, user_id: uuid.UUID):
        self.rt = rt
        self.run_id = run_id
        self.user_id = user_id

    async def add_usage(self, usage: UsageRecord) -> int:
        async with self.rt.sessionmaker() as session, session.begin():
            return await runs_repo.add_usage(session, self.run_id, self.user_id, usage)

    async def add_search(self) -> int:
        async with self.rt.sessionmaker() as session, session.begin():
            return await runs_repo.add_search(session, self.run_id)


def _config(run_id: uuid.UUID) -> RunnableConfig:
    return {"configurable": {"thread_id": str(run_id)}}


async def _claim(rt: WorkerRuntime, run_id: uuid.UUID, owner: str) -> Run | None:
    """Takes the lease and moves queued → running. A run that was already running had a
    worker die under it: announce the recovery and continue from its checkpoint."""
    async with rt.sessionmaker() as session, session.begin():
        run = await runs_repo.acquire_lease(session, run_id, owner, rt.settings.run_lease_ttl_s)
        if run is None:
            return None
        if run.status == RunStatus.QUEUED:
            await runs_service.transition(session, run.id, run.user_id, RunStatus.RUNNING)
        else:
            await events_repo.insert_event(
                session,
                run_id=run.id,
                user_id=run.user_id,
                data=RunStatusChanged(
                    status=RunStatus.RUNNING,
                    previous=RunStatus.RUNNING,
                    detail="Recovered after a worker stopped; continuing from the last checkpoint.",
                ),
            )
        await session.refresh(run)
        return run


async def _keep_lease(
    rt: WorkerRuntime, run_id: uuid.UUID, owner: str, job: asyncio.Task[Any]
) -> None:
    """Renews the lease until cancelled; if it is lost, stops the job so two workers never
    drive the same run."""
    interval = rt.settings.run_lease_ttl_s / 3
    while True:
        await asyncio.sleep(interval)
        try:
            async with rt.sessionmaker() as session, session.begin():
                held = await runs_repo.renew_lease(
                    session, run_id, owner, rt.settings.run_lease_ttl_s
                )
        except Exception:
            log.warning("run.lease_renew_failed", run_id=str(run_id), exc_info=True)
            continue
        if not held:
            log.error("run.lease_lost", run_id=str(run_id))
            job.cancel()
            return


async def _persist_checkpoint(
    rt: WorkerRuntime, run: Run, owner: str, payload: CheckpointPayload
) -> None:
    """Ideas + version 1, `idea.created` per new idea, `run.interrupted`, then the status
    change: one transaction, so a crash leaves either all of it or none (and a replay is a
    no-op because ideas are unique per (run, key))."""
    async with rt.sessionmaker() as session, session.begin():
        idea_ids: list[uuid.UUID] = []
        for brief in payload.briefs:
            idea_id, created = await ideas_repo.upsert_from_brief(
                session, run.id, run.user_id, brief
            )
            idea_ids.append(idea_id)
            if created:
                await events_repo.insert_event(
                    session,
                    run_id=run.id,
                    user_id=run.user_id,
                    data=IdeaCreated(
                        idea_id=idea_id,
                        key=brief.idea_id,
                        title=brief.opportunity.title,
                        rank=brief.rank,
                        composite_score=brief.composite_score,
                        version=1,
                    ),
                )
        await events_repo.insert_event(
            session,
            run_id=run.id,
            user_id=run.user_id,
            data=RunInterrupted(
                viable_count=payload.viable_count, shortfall=payload.shortfall, idea_ids=idea_ids
            ),
        )
        moved = await runs_service.transition(
            session,
            run.id,
            run.user_id,
            RunStatus.AWAITING_HUMAN,
            values={"viable_count": payload.viable_count, "shortfall": payload.shortfall},
            lease_owner=owner,
        )
        if not moved:
            # Lease lost to another job: roll back everything above; that job persists.
            raise LeaseLostError(run.id)


async def _complete(rt: WorkerRuntime, run: Run, owner: str) -> None:
    async with rt.sessionmaker() as session, session.begin():
        await events_repo.insert_event(
            session, run_id=run.id, user_id=run.user_id, data=RunCompleted()
        )
        if not await runs_service.transition(
            session, run.id, run.user_id, RunStatus.COMPLETED, lease_owner=owner
        ):
            raise LeaseLostError(run.id)


async def _drive_graph(rt: WorkerRuntime, run: Run, owner: str) -> None:
    settings = rt.settings
    events = PostgresEventSink(rt.sessionmaker, run.id, run.user_id)
    budget = RunBudget(
        max_tokens=run.max_tokens,
        max_searches=run.max_searches,
        tokens_used=run.tokens_used,
        searches_used=run.searches_used,
        store=PostgresUsageStore(rt, run.id, run.user_id),
        events=events,
    )
    deps = build_deps(
        settings,
        budget.record_usage,
        before_call=budget.before_llm_call,
        search_cache=PostgresSearchCache(rt.sessionmaker, run.id, run.user_id),
        before_search=budget.before_search,
        after_search=budget.record_search,
        events=events,
    )
    config = _config(run.id)
    # durability="sync": each step's checkpoint is committed before the next step starts,
    # so a killed worker loses at most the step that was running.
    async with postgres_checkpointer(settings) as saver:
        graph = compile_graph(saver)
        snapshot = await graph.aget_state(config)
        if not snapshot.values:
            initial: Phase1State = {
                "run_id": str(run.id),
                "run_input": RunInput.model_validate(run.input),
            }
            await graph.ainvoke(initial, config, context=deps, durability="sync")
        elif snapshot.next and not snapshot.interrupts:
            log.info("run.resume_from_checkpoint", run_id=str(run.id), next=list(snapshot.next))
            await graph.ainvoke(None, config, context=deps, durability="sync")
        snapshot = await graph.aget_state(config)

    if snapshot.interrupts:
        await _persist_checkpoint(
            rt, run, owner, CheckpointPayload.model_validate(snapshot.interrupts[0].value)
        )
    elif not snapshot.next:
        await _complete(rt, run, owner)


async def _stop(
    rt: WorkerRuntime,
    run: Run,
    owner: str,
    status: RunStatus,
    code: str,
    message: str,
    preceding: Sequence[EventData] = (),
) -> None:
    async with rt.sessionmaker() as session, session.begin():
        await runs_service.fail(
            session,
            run.id,
            run.user_id,
            code=code,
            message=message,
            status=status,
            preceding=preceding,
            only_from=[RunStatus.RUNNING],
            lease_owner=owner,
        )


async def execute_run(rt: WorkerRuntime, run_id: uuid.UUID, job_id: str) -> str:
    # The lease belongs to this job, not to the worker process: a worker can hold two jobs
    # for one run (arq's retry of a lost job plus a recovery job) and only one may drive it.
    owner = f"{rt.worker_id}/{job_id}"
    run = await _claim(rt, run_id, owner)
    if run is None:
        log.info("run.skipped", run_id=str(run_id), reason="not active or leased elsewhere")
        return "skipped"

    job = asyncio.current_task()
    assert job is not None
    lease = asyncio.create_task(_keep_lease(rt, run.id, owner, job))
    log.info("run.started", run_id=str(run.id), status=run.status.value)
    try:
        await _drive_graph(rt, run, owner)
    except BudgetExhaustedError as exc:
        log.info("run.budget_exhausted", run_id=str(run.id), kind=exc.kind)
        await _stop(
            rt,
            run,
            owner,
            RunStatus.BUDGET_EXHAUSTED,
            "budget_exhausted",
            str(exc),
            preceding=[exc.event()],
        )
        return RunStatus.BUDGET_EXHAUSTED.value
    except LeaseLostError:
        log.warning("run.lease_lost_before_commit", run_id=str(run.id))
        return "lease_lost"
    except asyncio.CancelledError:
        # Shutdown, job timeout or lost lease: leave the run active so it is recovered
        # from its checkpoint, and free the lease so that can happen without waiting.
        async with rt.sessionmaker() as session, session.begin():
            await asyncio.shield(runs_repo.release_lease(session, run.id, owner))
        raise
    except Exception as exc:
        log.exception("run.failed", run_id=str(run.id))
        message = f"{type(exc).__name__}: {exc}"[:1000]
        await _stop(rt, run, owner, RunStatus.FAILED, "run_failed", message)
        return RunStatus.FAILED.value
    finally:
        lease.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await lease

    async with rt.sessionmaker() as session:
        final = await runs_repo.get_any(session, run.id)
    status = final.status.value if final else "unknown"
    log.info("run.stopped", run_id=str(run.id), status=status)
    return status


async def recover_stale_runs(rt: WorkerRuntime, enqueue: Any) -> list[uuid.UUID]:
    """Re-enqueues runs whose worker died (expired lease) or whose job was lost."""
    async with rt.sessionmaker() as session:
        stale = list(await runs_repo.stale_runs(session, rt.settings.run_lease_ttl_s))
    for run_id in stale:
        await enqueue(
            START_RUN,
            str(run_id),
            _job_id=f"recover:{run_id}:{uuid.uuid4().hex[:8]}",
            _queue_name=rt.settings.arq_queue_name,
        )
    if stale:
        log.info("run.recovery_enqueued", run_ids=[str(r) for r in stale])
    return stale
