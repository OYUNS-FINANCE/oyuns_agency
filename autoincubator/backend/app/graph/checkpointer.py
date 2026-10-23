"""Postgres checkpointer (the only saver used outside unit tests)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings


@asynccontextmanager
async def postgres_checkpointer(settings: Settings) -> AsyncIterator[BaseCheckpointSaver[str]]:
    """Opens a connection, creates/migrates the checkpoint tables, yields the saver.

    The msgpack deserialisation allowlist is derived by LangGraph at compile() time from
    Phase1State's type hints, so every Pydantic model reachable from the state schema
    round-trips. Types put in state *outside* the schema would come back as dicts under
    LANGGRAPH_STRICT_MSGPACK; the integration test runs in strict mode to catch that.
    """
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url) as saver:
        await saver.setup()
        yield saver
