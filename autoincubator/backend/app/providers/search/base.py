"""Search provider protocol and a per-run result cache."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from pydantic import BaseModel

from app.core.types import WebUrl


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
        cached = await self.cache.get(key, max_results)
        if cached is not None:
            return cached
        if self.before_search is not None:
            await self.before_search(key)
        results = await self.inner.search(query, max_results=max_results)
        if self.after_search is not None:
            await self.after_search(key)
        await self.cache.put(key, max_results, results)
        return results
