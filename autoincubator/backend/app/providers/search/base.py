"""Search provider protocol and a per-run result cache."""

from __future__ import annotations

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


class CachedSearchProvider:
    """Wraps a provider so identical queries within one run hit the network once.

    In-memory for now; the persistent `search_cache` table arrives with the DB tables (Phase 2).
    """

    def __init__(self, inner: SearchProvider):
        self.inner = inner
        self._cache: dict[tuple[str, int], list[SearchResult]] = {}

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        key = (" ".join(query.lower().split()), max_results)
        if key not in self._cache:
            self._cache[key] = await self.inner.search(query, max_results=max_results)
        return self._cache[key]
