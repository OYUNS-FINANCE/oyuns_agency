"""Run lifecycle: creation, the status state machine, and read models. See ADR 0004.

queued ──► running ──► awaiting_human ──(Phase 4: select)──► running ──► completed
  │          │
  ▼          ├──► failed
failed       └──► budget_exhausted
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analyst.schemas import MarketAnalysis
from app.agents.common.schemas import RunInput
from app.agents.scout.schemas import RawOpportunity
from app.agents.skeptic.schemas import CritiqueScorecard
from app.core.config import Settings
from app.core.errors import NotFoundError
from app.db.enums import RunMode, RunStatus
from app.db.models import Run
from app.db.repositories import events as events_repo
from app.db.repositories import ideas as ideas_repo
from app.db.repositories import profile as profile_repo
from app.db.repositories import runs as runs_repo
from app.events.schema import EventData, RunErrored, RunStatusChanged
from app.services.schemas import (
    BudgetUsage,
    CreateRunRequest,
    IdeaView,
    RunDetail,
    RunErrorInfo,
    RunList,
    RunSummary,
)

START_RUN = "start_run"
"""arq job name of the worker task that executes a run."""

TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.FAILED}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.AWAITING_HUMAN,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.BUDGET_EXHAUSTED,
        }
    ),
    RunStatus.AWAITING_HUMAN: frozenset({RunStatus.RUNNING, RunStatus.FAILED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.BUDGET_EXHAUSTED: frozenset(),
}
FINISHED = frozenset(
    {
        RunStatus.AWAITING_HUMAN,
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.BUDGET_EXHAUSTED,
    }
)
"""Statuses in which no worker is executing the run (finished_at is set, lease cleared)."""


def allowed_from(to: RunStatus) -> list[RunStatus]:
    return [s for s, targets in TRANSITIONS.items() if to in targets]


async def transition(
    session: AsyncSession,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    to: RunStatus,
    *,
    detail: str | None = None,
    values: dict[str, Any] | None = None,
    only_from: Sequence[RunStatus] | None = None,
    lease_owner: str | None = None,
) -> bool:
    """Moves the run to `to` if the state machine allows it from its current status (further
    narrowed by `only_from`), and emits `run.status` in the same transaction. Returns False
    (and changes nothing) when the run was not in an allowed status, e.g. another worker
    already moved it, or when `lease_owner` is given and no longer holds the lease."""
    sources = [s for s in allowed_from(to) if only_from is None or s in only_from]
    extra = dict(values or {})
    if to == RunStatus.RUNNING:
        extra.setdefault("started_at", func.coalesce(Run.started_at, func.now()))
        extra["finished_at"] = None
    if to in FINISHED:
        extra.setdefault("finished_at", func.now())
        extra.update(lease_owner=None, lease_expires_at=None)
    previous = await runs_repo.update_status(
        session, run_id, allowed_from=sources, to=to, values=extra, lease_owner=lease_owner
    )
    if previous is None:
        return False
    await events_repo.insert_event(
        session,
        run_id=run_id,
        user_id=user_id,
        data=RunStatusChanged(status=to, previous=previous, detail=detail),
    )
    return True


async def fail(
    session: AsyncSession,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    code: str,
    message: str,
    status: RunStatus = RunStatus.FAILED,
    preceding: Sequence[EventData] = (),
    only_from: Sequence[RunStatus] | None = None,
    lease_owner: str | None = None,
) -> bool:
    """Terminal stop with the error stored on the run. Emits `preceding` events, `run.error`,
    then the final `run.status`, so the status change is always the last event of a stopped
    run. Nothing is emitted when the run was not in a status that can move to `status`."""
    async with session.begin_nested() as savepoint:
        for data in preceding:
            await events_repo.insert_event(session, run_id=run_id, user_id=user_id, data=data)
        await events_repo.insert_event(
            session, run_id=run_id, user_id=user_id, data=RunErrored(code=code, message=message)
        )
        moved = await transition(
            session,
            run_id,
            user_id,
            status,
            detail=message,
            values={"error": {"code": code, "message": message}},
            only_from=only_from,
            lease_owner=lease_owner,
        )
        if not moved:
            await savepoint.rollback()
    return moved


async def create_run(
    session: AsyncSession, user_id: uuid.UUID, request: CreateRunRequest, settings: Settings
) -> Run:
    """Inserts a queued run (and its first `run.status` event). The caller commits, then
    enqueues the worker job, so the worker always finds the row."""
    founder_profile = None
    if request.mode == "autonomous":
        stored = await profile_repo.get(session, user_id)
        founder_profile = stored[0] if stored else None
    run_input = RunInput(
        mode=request.mode,
        seed=request.seed,
        constraints=request.constraints,
        founder_profile=founder_profile,
    )
    budget = request.budget
    max_tokens = min(settings.run_max_tokens, (budget and budget.max_tokens) or 2**62)
    max_searches = min(settings.run_max_searches, (budget and budget.max_searches) or 2**31 - 1)
    run = Run(
        id=uuid.uuid4(),
        user_id=user_id,
        mode=RunMode(request.mode),
        seed=request.seed,
        input=run_input.model_dump(mode="json"),
        status=RunStatus.QUEUED,
        max_tokens=max_tokens,
        max_searches=max_searches,
    )
    session.add(run)
    await session.flush()
    await events_repo.insert_event(
        session,
        run_id=run.id,
        user_id=user_id,
        data=RunStatusChanged(status=RunStatus.QUEUED),
    )
    return run


def _summary_fields(run: Run) -> dict[str, Any]:
    return {
        "id": run.id,
        "mode": run.mode.value,
        "seed": run.seed,
        "status": run.status,
        "error": RunErrorInfo.model_validate(run.error) if run.error else None,
        "viable_count": run.viable_count,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


async def list_runs(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> RunList:
    rows, total = await runs_repo.list_for_user(session, user_id, limit=limit, offset=offset)
    return RunList(
        items=[RunSummary(**_summary_fields(r)) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = await runs_repo.get(session, run_id, user_id)
    if run is None:
        raise NotFoundError(f"run {run_id} not found")
    return run


async def run_detail(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> RunDetail:
    run = await get_run(session, user_id, run_id)
    cost = await runs_repo.total_cost(session, run.id)
    ideas = [
        IdeaView(
            id=idea.id,
            key=idea.key,
            status=idea.status,
            rank=idea.rank,
            composite_score=float(idea.composite_score)
            if idea.composite_score is not None
            else None,
            version=version.version,
            version_source=version.source,
            title=str(version.opportunity["title"]),
            opportunity=RawOpportunity.model_validate(version.opportunity),
            analysis=MarketAnalysis.model_validate(version.analysis),
            critique=CritiqueScorecard.model_validate(version.critique),
        )
        for idea, version in await ideas_repo.latest_for_run(session, run.id)
    ]
    return RunDetail(
        **_summary_fields(run),
        input=RunInput.model_validate(run.input),
        shortfall=run.shortfall,
        budget=BudgetUsage(
            max_tokens=run.max_tokens,
            tokens_used=run.tokens_used,
            max_searches=run.max_searches,
            searches_used=run.searches_used,
            cost_usd=float(cost),
        ),
        ideas=ideas,
    )
