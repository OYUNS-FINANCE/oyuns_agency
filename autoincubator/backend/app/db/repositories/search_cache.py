"""search_cache: per-run results keyed by normalised query."""

from __future__ import annotations

import uuid

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import SearchCacheEntry
from app.providers.search.base import SearchResult

_RESULTS: TypeAdapter[list[SearchResult]] = TypeAdapter(list[SearchResult])


class PostgresSearchCache:
    """`SearchCache` backed by the search_cache table, scoped to one run. Survives worker
    restarts, so nodes re-run after a crash do not pay for their searches again."""

    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], run_id: uuid.UUID, user_id: uuid.UUID
    ):
        self.sessionmaker = sessionmaker
        self.run_id = run_id
        self.user_id = user_id

    async def get(self, query_norm: str, max_results: int) -> list[SearchResult] | None:
        async with self.sessionmaker() as session:
            results = await session.scalar(
                select(SearchCacheEntry.results).where(
                    SearchCacheEntry.run_id == self.run_id,
                    SearchCacheEntry.query_norm == query_norm,
                    SearchCacheEntry.max_results == max_results,
                )
            )
        return None if results is None else _RESULTS.validate_python(results)

    async def put(self, query_norm: str, max_results: int, results: list[SearchResult]) -> None:
        async with self.sessionmaker() as session, session.begin():
            await session.execute(
                insert(SearchCacheEntry)
                .values(
                    run_id=self.run_id,
                    user_id=self.user_id,
                    query_norm=query_norm,
                    max_results=max_results,
                    results=_RESULTS.dump_python(results, mode="json"),
                )
                .on_conflict_do_nothing(index_elements=["run_id", "query_norm", "max_results"])
            )
