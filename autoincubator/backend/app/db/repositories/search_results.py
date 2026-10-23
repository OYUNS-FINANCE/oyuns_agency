"""search_result_cache: provider answers shared across runs, with a TTL."""

from __future__ import annotations

from datetime import timedelta

from pydantic import TypeAdapter
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import SearchResultCache
from app.providers.search.base import SearchResult

_RESULTS: TypeAdapter[list[SearchResult]] = TypeAdapter(list[SearchResult])


class PostgresResultCache:
    """`ResultStore` over Postgres. The TTL is applied on read, so changing it needs no
    cleanup; `purge` drops rows no TTL could still use."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], ttl_s: int):
        self.sessionmaker = sessionmaker
        self.ttl = timedelta(seconds=ttl_s)

    async def get(
        self, provider: str, query_norm: str, max_results: int
    ) -> list[SearchResult] | None:
        async with self.sessionmaker() as session:
            results = await session.scalar(
                select(SearchResultCache.results).where(
                    SearchResultCache.provider == provider,
                    SearchResultCache.query_norm == query_norm,
                    SearchResultCache.max_results == max_results,
                    SearchResultCache.fetched_at > func.now() - self.ttl,
                )
            )
        return None if results is None else _RESULTS.validate_python(results)

    async def put(
        self, provider: str, query_norm: str, max_results: int, results: list[SearchResult]
    ) -> None:
        dumped = _RESULTS.dump_python(results, mode="json")
        async with self.sessionmaker() as session, session.begin():
            stmt = insert(SearchResultCache).values(
                provider=provider, query_norm=query_norm, max_results=max_results, results=dumped
            )
            await session.execute(
                stmt.on_conflict_do_update(
                    index_elements=["provider", "query_norm", "max_results"],
                    set_={"results": dumped, "fetched_at": func.now()},
                )
            )

    async def purge(self, older_than: timedelta) -> int:
        async with self.sessionmaker() as session, session.begin():
            result = await session.execute(
                delete(SearchResultCache).where(
                    SearchResultCache.fetched_at < func.now() - older_than
                )
            )
        return int(getattr(result, "rowcount", 0) or 0)
