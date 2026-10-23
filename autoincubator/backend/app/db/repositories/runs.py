"""runs and run_costs: creation, reads, worker leases and usage counters."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import RunStatus
from app.db.models import Run, RunCost
from app.providers.llm.base import UsageRecord

ACTIVE_STATUSES = (RunStatus.QUEUED, RunStatus.RUNNING)


@dataclass(frozen=True)
class AgentCostRow:
    agent: str
    model: str
    calls: int
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cost_usd: Decimal


async def get(session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID) -> Run | None:
    run: Run | None = await session.scalar(
        select(Run).where(Run.id == run_id, Run.user_id == user_id)
    )
    return run


async def get_for_update(
    session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID
) -> Run | None:
    """Row-locks the run: co-working writes and select serialise on it (ADR 0006)."""
    run: Run | None = await session.scalar(
        select(Run)
        .where(Run.id == run_id, Run.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return run


async def get_any(session: AsyncSession, run_id: uuid.UUID) -> Run | None:
    """Worker-side read: the worker acts for whichever user owns the run."""
    return await session.get(Run, run_id, populate_existing=True)


async def list_for_user(
    session: AsyncSession, user_id: uuid.UUID, *, limit: int, offset: int
) -> tuple[Sequence[Run], int]:
    rows = await session.scalars(
        select(Run)
        .where(Run.user_id == user_id)
        .order_by(Run.created_at.desc(), Run.id)
        .limit(limit)
        .offset(offset)
    )
    total = await session.scalar(
        select(func.count()).select_from(Run).where(Run.user_id == user_id)
    )
    return rows.all(), total or 0


async def update_status(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    allowed_from: Sequence[RunStatus],
    to: RunStatus,
    values: dict[str, Any] | None = None,
    lease_owner: str | None = None,
) -> RunStatus | None:
    """Conditional transition. Returns the previous status, or None when the run was not
    in one of `allowed_from` (another worker moved it first, or the request is invalid) or,
    with `lease_owner`, when that lease is no longer held."""
    query = select(Run.status).where(Run.id == run_id)
    if lease_owner is not None:
        query = query.where(Run.lease_owner == lease_owner)
    previous = await session.scalar(query.with_for_update())
    if previous is None or previous not in allowed_from:
        return None
    await session.execute(update(Run).where(Run.id == run_id).values(status=to, **(values or {})))
    return previous


async def acquire_lease(
    session: AsyncSession, run_id: uuid.UUID, owner: str, ttl_s: float
) -> Run | None:
    """Claims an active run whose lease is free, expired, or already ours."""
    claimed = await session.scalar(
        update(Run)
        .where(
            Run.id == run_id,
            Run.status.in_(ACTIVE_STATUSES),
            or_(
                Run.lease_owner.is_(None),
                Run.lease_owner == owner,
                Run.lease_expires_at < func.now(),
            ),
        )
        .values(lease_owner=owner, lease_expires_at=func.now() + timedelta(seconds=ttl_s))
        .returning(Run.id)
    )
    if claimed is None:
        return None
    return await get_any(session, run_id)


async def renew_lease(session: AsyncSession, run_id: uuid.UUID, owner: str, ttl_s: float) -> bool:
    renewed = await session.scalar(
        update(Run)
        .where(Run.id == run_id, Run.lease_owner == owner)
        .values(lease_expires_at=func.now() + timedelta(seconds=ttl_s))
        .returning(Run.id)
    )
    return renewed is not None


async def release_lease(session: AsyncSession, run_id: uuid.UUID, owner: str) -> None:
    await session.execute(
        update(Run)
        .where(Run.id == run_id, Run.lease_owner == owner)
        .values(lease_owner=None, lease_expires_at=None)
    )


async def stale_runs(session: AsyncSession, queued_grace_s: float) -> Sequence[uuid.UUID]:
    """Runs that need a worker: running with an expired lease, or queued for too long
    without one (the enqueued job was lost)."""
    rows = await session.scalars(
        select(Run.id).where(
            or_(
                and_(Run.status == RunStatus.RUNNING, Run.lease_expires_at < func.now()),
                and_(
                    Run.status.in_(ACTIVE_STATUSES),
                    Run.lease_owner.is_(None),
                    Run.created_at < func.now() - timedelta(seconds=queued_grace_s),
                ),
            )
        )
    )
    return rows.all()


async def add_usage(
    session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID, usage: UsageRecord
) -> int:
    """Records one LLM attempt and returns the run's new token total."""
    tokens = (
        usage.input_tokens
        + usage.output_tokens
        + usage.cache_read_input_tokens
        + usage.cache_creation_input_tokens
    )
    session.add(
        RunCost(
            run_id=run_id,
            user_id=user_id,
            agent=usage.agent,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            cost_usd=Decimal(str(usage.cost_usd)),
            attempt=usage.attempt,
        )
    )
    total = await session.scalar(
        update(Run)
        .where(Run.id == run_id)
        .values(tokens_used=Run.tokens_used + tokens)
        .returning(Run.tokens_used)
    )
    return int(total or 0)


async def add_search(session: AsyncSession, run_id: uuid.UUID) -> int:
    total = await session.scalar(
        update(Run)
        .where(Run.id == run_id)
        .values(searches_used=Run.searches_used + 1)
        .returning(Run.searches_used)
    )
    return int(total or 0)


async def total_cost(session: AsyncSession, run_id: uuid.UUID) -> Decimal:
    total = await session.scalar(
        select(func.coalesce(func.sum(RunCost.cost_usd), 0)).where(RunCost.run_id == run_id)
    )
    return Decimal(total or 0)


async def spent_today(session: AsyncSession) -> Decimal:
    """Global LLM spend since 00:00 UTC, across every run and user."""
    midnight = func.timezone("UTC", func.date_trunc("day", func.timezone("UTC", func.now())))
    total = await session.scalar(
        select(func.coalesce(func.sum(RunCost.cost_usd), 0)).where(RunCost.created_at >= midnight)
    )
    return Decimal(total or 0)


async def cost_by_agent(session: AsyncSession, run_id: uuid.UUID) -> list[AgentCostRow]:
    """Spend per (agent, model); sub-agents (`scout.plan`, `scout.extract`) are separate rows."""
    rows = await session.execute(
        select(
            RunCost.agent,
            RunCost.model,
            func.count(),
            func.sum(RunCost.input_tokens),
            func.sum(RunCost.output_tokens),
            func.sum(RunCost.cache_read_input_tokens),
            func.sum(RunCost.cost_usd),
        )
        .where(RunCost.run_id == run_id)
        .group_by(RunCost.agent, RunCost.model)
        .order_by(func.sum(RunCost.cost_usd).desc())
    )
    return [
        AgentCostRow(
            agent=agent,
            model=model,
            calls=int(calls),
            input_tokens=int(tin or 0),
            output_tokens=int(tout or 0),
            cache_read_input_tokens=int(tcache or 0),
            cost_usd=Decimal(cost or 0),
        )
        for agent, model, calls, tin, tout, tcache, cost in rows.all()
    ]
