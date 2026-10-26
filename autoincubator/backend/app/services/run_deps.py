"""GraphDeps for one run, with its budget, search cache and event sink wired to Postgres.

Shared by the worker (graph runs and co-working jobs) and the API (co-working chat), so
every LLM call and search made for a run is charged to the same budget (ADR 0004, 0006).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.models import Run
from app.db.repositories import runs as runs_repo
from app.db.repositories.search_cache import PostgresSearchCache
from app.db.repositories.search_results import PostgresResultCache
from app.events.publisher import PostgresEventSink
from app.graph.deps import GraphDeps
from app.providers.factory import build_deps
from app.providers.llm.base import UsageRecord
from app.services.budget import RunBudget
from app.services.llm_settings import effective_settings


class PostgresUsageStore:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID, user_id: uuid.UUID
    ):
        self.sessionmaker = sessionmaker
        self.run_id = run_id
        self.user_id = user_id

    async def add_usage(self, usage: UsageRecord) -> int:
        async with self.sessionmaker() as session, session.begin():
            return await runs_repo.add_usage(session, self.run_id, self.user_id, usage)

    async def add_search(self) -> int:
        async with self.sessionmaker() as session, session.begin():
            return await runs_repo.add_search(session, self.run_id)

    async def spent_today_usd(self) -> float:
        async with self.sessionmaker() as session:
            return float(await runs_repo.spent_today(session))


async def run_deps(
    settings: Settings, sessionmaker: async_sessionmaker[AsyncSession], run: Run
) -> tuple[GraphDeps, RunBudget]:
    """The LLM provider and models come from the user's saved UI configuration when there is
    one, else from the environment; a run keeps what it resolved here for its whole life."""
    settings = await effective_settings(sessionmaker, settings, run.user_id)
    events = PostgresEventSink(sessionmaker, run.id, run.user_id)
    budget = RunBudget(
        max_tokens=run.max_tokens,
        max_searches=run.max_searches,
        tokens_used=run.tokens_used,
        searches_used=run.searches_used,
        store=PostgresUsageStore(sessionmaker, run.id, run.user_id),
        events=events,
        daily_cap_usd=settings.daily_cost_cap_usd,
    )
    deps = build_deps(
        settings,
        budget.record_usage,
        before_call=budget.before_llm_call,
        search_cache=PostgresSearchCache(sessionmaker, run.id, run.user_id),
        result_store=PostgresResultCache(sessionmaker, settings.search_cache_ttl_s),
        before_search=budget.before_search,
        after_search=budget.record_search,
        events=events,
    )
    return deps, budget
