"""agent_events: ordered inserts with NOTIFY, and cursor reads. See ADR 0003."""

from __future__ import annotations

import uuid

from sqlalchemy import func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentEventRow
from app.events.schema import EVENT_ADAPTER, Event, EventData

NOTIFY_CHANNEL = "agent_events"


async def insert_event(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    data: EventData,
    agent: str | None = None,
) -> int:
    """Insert one event and NOTIFY listeners; both take effect when the caller commits.

    The per-run advisory lock is taken *before* the id is drawn from the sequence and held
    until commit, so for any one run, id order equals commit order. A reader that has seen
    id N can therefore never later see a committed id < N appear for that run.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"run-events:{run_id}"}
    )
    event_id = await session.scalar(
        insert(AgentEventRow)
        .values(
            run_id=run_id,
            user_id=user_id,
            type=data.event_type,
            agent=agent,
            data=data.model_dump(mode="json"),
        )
        .returning(AgentEventRow.id)
    )
    assert event_id is not None
    await session.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": NOTIFY_CHANNEL, "payload": f"{run_id}:{event_id}"},
    )
    return event_id


def to_event(row: AgentEventRow) -> Event:
    return EVENT_ADAPTER.validate_python(
        {
            "id": row.id,
            "run_id": row.run_id,
            "ts": row.created_at,
            "agent": row.agent,
            "type": row.type,
            "data": row.data,
        }
    )


async def list_after(
    session: AsyncSession, run_id: uuid.UUID, after: int, limit: int = 500
) -> list[Event]:
    rows = await session.scalars(
        select(AgentEventRow)
        .where(AgentEventRow.run_id == run_id, AgentEventRow.id > after)
        .order_by(AgentEventRow.id)
        .limit(limit)
    )
    return [to_event(r) for r in rows]


async def count_by_type(session: AsyncSession, run_id: uuid.UUID) -> dict[str, int]:
    rows = await session.execute(
        select(AgentEventRow.type, func.count())
        .where(AgentEventRow.run_id == run_id)
        .group_by(AgentEventRow.type)
    )
    return {t: n for t, n in rows.tuples()}
