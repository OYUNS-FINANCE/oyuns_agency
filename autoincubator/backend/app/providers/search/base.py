"""Search provider protocol and a per-run result cache."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

import structlog
from opentelemetry import trace
from pydantic import BaseModel

from app.core.types import WebUrl

log = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class SearchResult(BaseModel):
    title: str
    url: WebUrl
    snippet: str
    published: str | None = None


class SearchProvider(Protocol):
    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]: ...


SearchHook = Callable[[str], Awaitable[None]]
"""Called with the normalised query around a provider call (cache misses only)."""


def normalise_query(query: str) -> str:
    return " ".join(query.lower().split())


class SearchCache(Protocol):
    async def get(self, query_norm: str, max_results: int) -> list[SearchResult] | None: ...
    async def put(self, query_norm: str, max_results: int, results: list[SearchResult]) -> None: ...


class InMemorySearchCache:
    def __init__(self) -> None:
        self._entries: dict[tuple[str, int], list[SearchResult]] = {}

    async def get(self, query_norm: str, max_results: int) -> list[SearchResult] | None:
        return self._entries.get((query_norm, max_results))

    async def put(self, query_norm: str, max_results: int, results: list[SearchResult]) -> None:
        self._entries[(query_norm, max_results)] = results


class CachedSearchProvider:
    """Wraps a provider so identical queries within one run hit the network once.

    `before_search` runs before every cache miss (budget check; it may raise) and
    `after_search` after the provider answered (budget accounting). Cache hits are free.
    """

    def __init__(
        self,
        inner: SearchProvider,
        cache: SearchCache | None = None,
        *,
        before_search: SearchHook | None = None,
        after_search: SearchHook | None = None,
    ):
        self.inner = inner
        self.cache: SearchCache = cache or InMemorySearchCache()
        self.before_search = before_search
        self.after_search = after_search

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        key = normalise_query(query)
        with tracer.start_as_current_span("search") as span:
            span.set_attribute("search.query", key[:200])
            cached = await self.cache.get(key, max_results)
            if cached is not None:
                span.set_attribute("search.run_cache_hit", True)
                span.set_attribute("search.result_count", len(cached))
                return cached
            span.set_attribute("search.run_cache_hit", False)
            if self.before_search is not None:
                await self.before_search(key)
            results = await self.inner.search(query, max_results=max_results)
            if self.after_search is not None:
                await self.after_search(key)
            await self.cache.put(key, max_results, results)
            span.set_attribute("search.result_count", len(results))
            return results


class ResultStore(Protocol):
    """Cross-run store of provider answers, keyed by provider and normalised query."""

    async def get(
        self, provider: str, query_norm: str, max_results: int
    ) -> list[SearchResult] | None: ...
    async def put(
        self, provider: str, query_norm: str, max_results: int, results: list[SearchResult]
    ) -> None: ...


class StoredSearchProvider:
    """Serves repeated queries from a `ResultStore` (across runs, within its TTL) and stores
    what the provider returns. A store failure is logged and never fails the search."""

    def __init__(self, inner: SearchProvider, store: ResultStore, provider_name: str):
        self.inner = inner
        self.store = store
        self.provider_name = provider_name

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        key = normalise_query(query)
        try:
            hit = await self.store.get(self.provider_name, key, max_results)
        except Exception:
            log.warning("search.store_read_failed", exc_info=True)
            hit = None
        if hit is not None:
            return hit
        results = await self.inner.search(query, max_results=max_results)
        try:
            await self.store.put(self.provider_name, key, max_results, results)
        except Exception:
            log.warning("search.store_write_failed", exc_info=True)
        return results
