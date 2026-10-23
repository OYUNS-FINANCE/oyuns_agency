"""Daily cost cap, per-agent cost and the cross-run search cache against Postgres."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.errors import TooManyRequestsError
from app.db.models import Run, SearchResultCache
from app.db.repositories import runs as runs_repo
from app.db.repositories.search_results import PostgresResultCache
from app.db.session import create_engine, create_sessionmaker
from app.events.sink import RecordingEventSink
from app.providers.llm.base import UsageRecord
from app.providers.search.base import SearchResult, StoredSearchProvider
from app.services import runs as runs_service
from app.services.budget import BudgetExhaustedError, RunBudget
from app.services.run_deps import PostgresUsageStore
from app.services.schemas import CreateRunRequest

pytestmark = pytest.mark.integration

USER = uuid.uuid4()
PROVIDER = f"test-{uuid.uuid4().hex[:8]}"


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
                delete(SearchResultCache).where(SearchResultCache.provider == PROVIDER)
            )
        await engine.dispose()


def _usage(agent: str, cost: float, model: str = "claude-sonnet-5-5") -> UsageRecord:
    return UsageRecord(
        agent=agent, model=model, input_tokens=1000, output_tokens=100, cost_usd=cost
    )


async def _run(sm: async_sessionmaker[AsyncSession], settings: Settings) -> uuid.UUID:
    async with sm() as session, session.begin():
        run = await runs_service.create_run(
            session, USER, CreateRunRequest(mode="seeded", seed="dental"), settings
        )
        return run.id


async def test_daily_cap_refuses_new_runs_and_stops_running_ones(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    async with sm() as session:
        before = float(await runs_repo.spent_today(session))
    settings = Settings(_env_file=None, daily_cost_cap_usd=before + 1.0)
    run_id = await _run(sm, settings)  # under the cap: accepted

    store = PostgresUsageStore(sm, run_id, USER)
    budget = RunBudget(
        max_tokens=10**9,
        max_searches=10,
        tokens_used=0,
        searches_used=0,
        store=store,
        events=RecordingEventSink(),
        daily_cap_usd=settings.daily_cost_cap_usd,
    )
    await budget.before_llm_call("scout.plan")
    await budget.record_usage(_usage("scout.plan", 1.5))  # another run's spend counts too

    with pytest.raises(BudgetExhaustedError) as stopped:
        await budget.before_llm_call("scout.plan")
    assert stopped.value.kind == "daily_cost"
    async with sm() as session, session.begin():
        with pytest.raises(TooManyRequestsError) as refused:
            await runs_service.create_run(
                session, USER, CreateRunRequest(mode="seeded", seed="dental"), settings
            )
    assert refused.value.code == "daily_cap_reached"

    off = Settings(_env_file=None, daily_cost_cap_usd=0)
    await _run(sm, off)  # 0 disables the cap


async def test_run_detail_reports_cost_per_agent_and_the_daily_figures(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    settings = Settings(_env_file=None, daily_cost_cap_usd=10_000.0)
    run_id = await _run(sm, settings)
    store = PostgresUsageStore(sm, run_id, USER)
    await store.add_usage(_usage("scout.plan", 0.01, "claude-haiku-5-5"))
    await store.add_usage(_usage("scout.extract", 0.02, "claude-haiku-5-5"))
    await store.add_usage(_usage("skeptic", 0.30, "claude-opus-5-5"))
    await store.add_usage(_usage("skeptic", 0.20, "claude-opus-5-5"))
    async with sm() as session:
        detail = await runs_service.run_detail(session, USER, run_id, settings)
    rows = detail.budget.cost_by_agent
    assert [r.agent for r in rows] == ["skeptic", "scout.extract", "scout.plan"]
    assert rows[0].calls == 2 and rows[0].cost_usd == pytest.approx(0.50)
    assert detail.budget.cost_usd == pytest.approx(0.53)
    assert detail.budget.daily_cap_usd == 10_000.0
    assert detail.budget.daily_spent_usd >= 0.53


class CountingSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.calls += 1
        return [SearchResult(title="t", url="https://a.example/x", snippet=query)]


async def test_result_cache_is_shared_across_runs_and_expires(
    sm: async_sessionmaker[AsyncSession],
) -> None:
    store = PostgresResultCache(sm, ttl_s=3600)
    inner = CountingSearch()
    await StoredSearchProvider(inner, store, PROVIDER).search("dental no shows")
    again = await StoredSearchProvider(inner, store, PROVIDER).search("DENTAL  no shows")
    assert inner.calls == 1 and again[0].snippet == "dental no shows"

    expired = PostgresResultCache(sm, ttl_s=1)
    await asyncio.sleep(1.2)
    assert await expired.get(PROVIDER, "dental no shows", 5) is None
    await StoredSearchProvider(inner, expired, PROVIDER).search("dental no shows")
    assert inner.calls == 2

    assert await store.purge(timedelta(seconds=0)) >= 1
