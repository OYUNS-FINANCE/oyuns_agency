"""Async token bucket: callers wait for a token instead of failing."""

from __future__ import annotations

import asyncio
import time


class AsyncRateLimiter:
    """`rate_per_s` sustained, with a burst of at most `burst` (default: one second's worth).

    Per process: with several workers the provider sees the sum of their rates.
    """

    def __init__(self, rate_per_s: float, burst: int | None = None):
        if rate_per_s <= 0:
            raise ValueError("rate_per_s must be positive")
        self.rate = rate_per_s
        self.capacity = float(burst if burst is not None else max(1, round(rate_per_s)))
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self.rate)
