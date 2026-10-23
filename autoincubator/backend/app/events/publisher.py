"""EventSink that persists to agent_events (one short transaction per event)."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.repositories.events import insert_event
from app.events.schema import EventData


class PostgresEventSink:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID, user_id: uuid.UUID
    ):
        self.sessionmaker = sessionmaker
        self.run_id = run_id
        self.user_id = user_id

    async def emit(self, data: EventData, *, agent: str | None = None) -> None:
        async with self.sessionmaker() as session, session.begin():
            await insert_event(
                session, run_id=self.run_id, user_id=self.user_id, data=data, agent=agent
            )
