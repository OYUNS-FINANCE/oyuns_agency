"""Tavily/Serper request and response handling, retries, timeouts, rate limit, caches.
Everything runs against httpx.MockTransport: no network."""

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.providers.search import http as search_http
from app.providers.search.base import SearchResult, StoredSearchProvider
from app.providers.search.factory import MissingSearchKeyError, build_search
from app.providers.search.http import SearchProviderError, backoff_seconds, retry_after_seconds
from app.providers.search.ratelimit import AsyncRateLimiter
from app.providers.search.serper import SerperSearch
from app.providers.search.tavily import TavilySearch

TAVILY_OK = {
    "results": [
        {
            "title": "A",
            "url": "https://a.example/1",
            "content": "alpha",
            "published_date": "2026-01-02",
        },
        {"title": "B", "url": "not a url", "content": "dropped"},
        {"title": "C", "url": "https://c.example/3", "content": "gamma"},
    ]
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(search_http, "_sleep", fake_sleep)
    return delays


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_tavily_request_shape_and_parsing() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=TAVILY_OK)

    search = TavilySearch("tvly-key", client=_client(handler))
    results = await search.search("dental no-shows", max_results=3)
    request = seen[0]
    assert str(request.url) == "https://api.tavily.com/search"
    assert request.headers["authorization"] == "Bearer tvly-key"
    body = json.loads(request.content)
    assert body["query"] == "dental no-shows" and body["max_results"] == 3
    assert body["include_raw_content"] is False and body["include_answer"] is False
    assert [r.url for r in results] == ["https://a.example/1", "https://c.example/3"]
    assert results[0].published == "2026-01-02" and results[0].snippet == "alpha"


async def test_serper_request_shape_and_parsing() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        organic = [
            {"title": "X", "link": "https://x.example/", "snippet": "s", "date": "Jan 1, 2026"}
        ]
        return httpx.Response(200, json={"organic": organic})

    results = await SerperSearch("k", client=_client(handler)).search("q", max_results=7)
    assert str(seen[0].url) == "https://google.serper.dev/search"
    assert seen[0].headers["x-api-key"] == "k"
    assert json.loads(seen[0].content) == {"q": "q", "num": 7}
    assert results == [
        SearchResult(title="X", url="https://x.example/", snippet="s", published="Jan 1, 2026")
    ]


async def test_retries_429_and_5xx_with_backoff_then_succeeds(no_sleep: list[float]) -> None:
    statuses = iter([429, 503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses)
        if status == 200:
            return httpx.Response(200, json=TAVILY_OK)
        return httpx.Response(status, headers={"retry-after": "2"} if status == 429 else {})

    search = TavilySearch("k", client=_client(handler), max_retries=3)
    assert len(await search.search("q")) == 2
    assert len(no_sleep) == 2 and no_sleep[0] >= 2.0  # Retry-After is honoured


async def test_gives_up_after_max_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    search = TavilySearch("k", client=_client(handler), max_retries=2)
    with pytest.raises(SearchProviderError, match="gave up after 3 attempts"):
        await search.search("q")
    assert calls == 3


async def test_timeouts_are_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=TAVILY_OK)

    assert await TavilySearch("k", client=_client(handler)).search("q")
    assert calls == 2


@pytest.mark.parametrize("status", [400, 401, 432])
async def test_client_errors_fail_immediately(status: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="nope")

    with pytest.raises(SearchProviderError) as exc:
        await TavilySearch("k", client=_client(handler)).search("q")
    assert calls == 1 and exc.value.status_code == status


async def test_non_json_answer_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>captcha</html>")

    with pytest.raises(SearchProviderError, match="not JSON"):
        await TavilySearch("k", client=_client(handler)).search("q")


def test_an_api_key_is_required() -> None:
    with pytest.raises(ValueError, match="API key"):
        TavilySearch("")


def test_backoff_grows_is_capped_and_respects_retry_after() -> None:
    assert backoff_seconds(1, 0.5, None) < backoff_seconds(4, 0.5, None)
    assert backoff_seconds(20, 0.5, None) <= search_http.MAX_BACKOFF_S
    assert backoff_seconds(1, 0.5, 10.0) >= 10.0
    assert retry_after_seconds(httpx.Response(429, headers={"retry-after": "7"})) == 7.0
    assert retry_after_seconds(httpx.Response(429, headers={"retry-after": "Wed, 21 Oct"})) is None


async def test_rate_limiter_spaces_calls_after_the_burst() -> None:
    limiter = AsyncRateLimiter(rate_per_s=20, burst=2)
    started = time.monotonic()
    for _ in range(4):
        await limiter.acquire()
    # two immediate, then two at 20/s: at least ~0.09s, far below a second
    elapsed = time.monotonic() - started
    assert 0.07 <= elapsed < 0.5


async def test_provider_waits_on_the_limiter() -> None:
    class Counting(AsyncRateLimiter):
        acquired = 0

        async def acquire(self) -> None:
            Counting.acquired += 1

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=TAVILY_OK)

    await TavilySearch("k", client=_client(handler), limiter=Counting(5)).search("q")
    assert Counting.acquired == 1


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[tuple[str, str, int], list[SearchResult]] = {}
        self.fail = False

    async def get(self, provider: str, q: str, n: int) -> list[SearchResult] | None:
        if self.fail:
            raise ConnectionError("db down")
        return self.data.get((provider, q, n))

    async def put(self, provider: str, q: str, n: int, results: list[SearchResult]) -> None:
        if self.fail:
            raise ConnectionError("db down")
        self.data[(provider, q, n)] = results


class CountingSearch:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        self.calls += 1
        return [SearchResult(title="t", url="https://a.example/", snippet=query)]


async def test_stored_provider_serves_repeats_across_runs() -> None:
    inner, store = CountingSearch(), MemoryStore()
    first = StoredSearchProvider(inner, store, "tavily")
    second = StoredSearchProvider(inner, store, "tavily")  # another run, same store
    await first.search("Dental  Clinics")
    await second.search("dental clinics")
    assert inner.calls == 1
    await StoredSearchProvider(inner, store, "serper").search("dental clinics")
    assert inner.calls == 2  # providers do not share entries


async def test_a_broken_store_never_fails_the_search() -> None:
    inner, store = CountingSearch(), MemoryStore()
    store.fail = True
    results = await StoredSearchProvider(inner, store, "tavily").search("q")
    assert len(results) == 1


def _settings(**kw: Any) -> Settings:
    return Settings(_env_file=None, **kw)


def test_real_provider_without_a_key_fails_loudly() -> None:
    with pytest.raises(MissingSearchKeyError, match="TAVILY_API_KEY"):
        build_search(_settings(search_provider="tavily"))
    with pytest.raises(MissingSearchKeyError, match="SERPER_API_KEY"):
        build_search(_settings(search_provider="serper"))


async def test_built_chain_sanitises_what_the_provider_returns() -> None:
    chain = build_search(_settings(search_provider="mock"))
    results = await chain.search("market size trend competitor complaint", max_results=20)
    assert results and all("Ignore all previous instructions" not in r.title for r in results)
