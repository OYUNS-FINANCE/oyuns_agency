"""Builds the search provider chain from settings.

    CachedSearchProvider      per-run cache + budget hooks (free hits)
      └ SanitizingSearch      markup/injection hygiene, length caps
          └ StoredSearchProvider   cross-run TTL cache (real providers only)
              └ TavilySearch | SerperSearch | MockSearchProvider

Sanitising sits outside the stored cache, so a tightened rule also cleans old entries.
"""

from __future__ import annotations

import httpx

from app.core.config import Settings
from app.providers.search.base import ResultStore, SearchProvider, StoredSearchProvider
from app.providers.search.http import HttpSearchProvider
from app.providers.search.mock import MockSearchProvider
from app.providers.search.ratelimit import AsyncRateLimiter
from app.providers.search.sanitize import SanitizingSearch
from app.providers.search.serper import SerperSearch
from app.providers.search.tavily import TavilySearch

_limiters: dict[str, AsyncRateLimiter] = {}
_clients: dict[str, httpx.AsyncClient] = {}


class MissingSearchKeyError(RuntimeError):
    pass


def _shared(name: str, settings: Settings) -> tuple[AsyncRateLimiter, httpx.AsyncClient]:
    """One limiter and connection pool per provider per process, shared by every run."""
    if name not in _limiters:
        _limiters[name] = AsyncRateLimiter(settings.search_rate_per_s)
        _clients[name] = httpx.AsyncClient(timeout=settings.search_timeout_s)
    return _limiters[name], _clients[name]


async def aclose_shared_clients() -> None:
    clients = list(_clients.values())
    _clients.clear()
    _limiters.clear()
    for client in clients:
        await client.aclose()


def _http_provider(settings: Settings) -> HttpSearchProvider:
    name = settings.search_provider
    secret = settings.tavily_api_key if name == "tavily" else settings.serper_api_key
    key = secret.get_secret_value() if secret else ""
    if not key:
        raise MissingSearchKeyError(
            f"SEARCH_PROVIDER={name} needs {name.upper()}_API_KEY to be set"
        )
    limiter, client = _shared(name, settings)
    cls = TavilySearch if name == "tavily" else SerperSearch
    return cls(key, client=client, max_retries=settings.search_max_retries, limiter=limiter)


def build_search(settings: Settings, store: ResultStore | None = None) -> SearchProvider:
    provider: SearchProvider
    if settings.search_provider == "mock":
        provider = MockSearchProvider()
    else:
        http_provider = _http_provider(settings)
        provider = http_provider
        if store is not None and settings.search_cache_ttl_s > 0:
            provider = StoredSearchProvider(http_provider, store, http_provider.name)
    return SanitizingSearch(
        provider,
        snippet_max_chars=settings.search_snippet_max_chars,
        title_max_chars=settings.search_title_max_chars,
    )
