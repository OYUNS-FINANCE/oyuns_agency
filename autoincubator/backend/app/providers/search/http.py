"""Shared HTTP plumbing for search providers: timeout, retries with backoff, rate limit."""

from __future__ import annotations

import abc
import asyncio
import random
from typing import Any

import httpx
import structlog
from opentelemetry import trace

from app.providers.search.base import SearchResult
from app.providers.search.ratelimit import AsyncRateLimiter

log = structlog.get_logger(__name__)
_sleep = asyncio.sleep  # a module attribute so tests can replace it without touching asyncio
tracer = trace.get_tracer(__name__)

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_BACKOFF_S = 30.0


class SearchProviderError(RuntimeError):
    """The provider could not answer (after retries, or the failure is not retryable)."""

    def __init__(self, provider: str, message: str, *, status_code: int | None = None):
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status_code = status_code


def retry_after_seconds(response: httpx.Response) -> float | None:
    value: str | None = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None  # an HTTP-date; fall back to the computed backoff


def backoff_seconds(attempt: int, base: float, retry_after: float | None) -> float:
    computed: float = min(MAX_BACKOFF_S, base * 2.0 ** (attempt - 1))
    computed += random.uniform(0, computed / 4)
    return min(MAX_BACKOFF_S, max(computed, retry_after or 0.0))


class HttpSearchProvider(abc.ABC):
    """Subclasses say how to build the request and parse the answer; this class does the rest.

    Failures that are retried: timeouts, connection errors, 408/425/429/5xx (honouring
    `Retry-After`). Everything else (bad key, quota, bad request) fails at once.
    """

    name: str
    url: str

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_s: float = 15.0,
        max_retries: int = 3,
        backoff_base_s: float = 0.5,
        limiter: AsyncRateLimiter | None = None,
    ):
        if not api_key:
            raise ValueError(f"{self.name}: an API key is required")
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(timeout=timeout_s)
        self._owns_client = client is None
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.limiter = limiter

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @abc.abstractmethod
    def _headers(self) -> dict[str, str]: ...

    @abc.abstractmethod
    def _body(self, query: str, max_results: int) -> dict[str, Any]: ...

    @abc.abstractmethod
    def _parse(self, payload: dict[str, Any]) -> list[SearchResult]: ...

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        with tracer.start_as_current_span(f"search.{self.name}") as span:
            span.set_attribute("search.provider", self.name)
            span.set_attribute("search.max_results", max_results)
            payload = await self._post(query, max_results)
            results = self._parse(payload)[:max_results]
            span.set_attribute("search.result_count", len(results))
            return results

    async def _post(self, query: str, max_results: int) -> dict[str, Any]:
        attempts = self.max_retries + 1
        last = "no attempt made"
        for attempt in range(1, attempts + 1):
            if self.limiter is not None:
                await self.limiter.acquire()
            retry_after: float | None = None
            try:
                response = await self._client.post(
                    self.url, headers=self._headers(), json=self._body(query, max_results)
                )
            except httpx.TransportError as exc:  # timeouts, connect/read errors
                last = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 200:
                    try:
                        payload = response.json()
                    except ValueError as exc:
                        raise SearchProviderError(self.name, "response was not JSON") from exc
                    if not isinstance(payload, dict):
                        raise SearchProviderError(self.name, "unexpected response shape")
                    return payload
                last = f"HTTP {response.status_code}"
                if response.status_code not in RETRYABLE_STATUS:
                    raise SearchProviderError(
                        self.name,
                        f"{last}: {response.text[:200]}",
                        status_code=response.status_code,
                    )
                retry_after = retry_after_seconds(response)
            if attempt < attempts:
                delay = backoff_seconds(attempt, self.backoff_base_s, retry_after)
                log.warning(
                    "search.retry", provider=self.name, attempt=attempt, reason=last, delay_s=delay
                )
                await _sleep(delay)
        raise SearchProviderError(self.name, f"gave up after {attempts} attempts ({last})")
