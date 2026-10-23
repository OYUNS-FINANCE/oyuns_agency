"""cowork_messages."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import CoworkAgent, CoworkMessageState, CoworkRole
from app.db.models import CoworkMessage

HISTORY_LIMIT = 40
"""A user message and its reply share `created_at` (one transaction); `role` breaks the tie,
and Postgres orders enum values by declaration: user before assistant."""


async def add(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    idea_id: uuid.UUID,
    user_id: uuid.UUID,
    agent: CoworkAgent,
    role: CoworkRole,
    state: CoworkMessageState,
    content: str,
    based_on_version: int,
) -> CoworkMessage:
    row = CoworkMessage(
        id=uuid.uuid4(),
        run_id=run_id,
        idea_id=idea_id,
        user_id=user_id,
        agent=agent,
        role=role,
        state=state,
        content=content,
        based_on_version=based_on_version,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def get(
    session: AsyncSession, idea_id: uuid.UUID, message_id: uuid.UUID
) -> CoworkMessage | None:
    row: CoworkMessage | None = await session.scalar(
        select(CoworkMessage).where(
            CoworkMessage.id == message_id, CoworkMessage.idea_id == idea_id
        )
    )
    return row


async def for_idea(session: AsyncSession, idea_id: uuid.UUID) -> Sequence[CoworkMessage]:
    rows = await session.scalars(
        select(CoworkMessage)
        .where(CoworkMessage.idea_id == idea_id)
        .order_by(CoworkMessage.created_at, CoworkMessage.role, CoworkMessage.id)
    )
    return rows.all()


async def history(session: AsyncSession, idea_id: uuid.UUID) -> Sequence[CoworkMessage]:
    """The last completed turns, oldest first: what the agent sees of the conversation."""
    rows = await session.scalars(
        select(CoworkMessage)
        .where(
            CoworkMessage.idea_id == idea_id,
            CoworkMessage.state == CoworkMessageState.COMPLETE,
        )
        .order_by(CoworkMessage.created_at.desc(), CoworkMessage.role.desc())
        .limit(HISTORY_LIMIT)
    )
    return list(reversed(rows.all()))


async def has_pending(session: AsyncSession, idea_id: uuid.UUID, timeout_s: float) -> bool:
    """A reply is being generated for this idea. Pending rows older than the reply timeout
    belong to a process that died, and no longer block new messages."""
    found = await session.scalar(
        select(CoworkMessage.id).where(
            CoworkMessage.idea_id == idea_id,
            CoworkMessage.state == CoworkMessageState.PENDING,
            CoworkMessage.created_at > func.now() - timedelta(seconds=timeout_s),
        )
    )
    return found is not None


async def finish(
    session: AsyncSession,
    message_id: uuid.UUID,
    *,
    state: CoworkMessageState,
    content: str,
    proposed_patch: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> None:
    await session.execute(
        update(CoworkMessage)
        .where(CoworkMessage.id == message_id)
        .values(state=state, content=content, proposed_patch=proposed_patch, error=error)
    )
