"""Rate limiting of public endpoints (ADR 0008): fixed windows in Redis, per client.

A client is the socket peer, or, behind reverse proxies, the address `TRUSTED_PROXY_HOPS`
entries from the right of X-Forwarded-For (anything further left is client-controlled and
ignored). Redis being down fails open: a limiter outage must not take the API down.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, cast

from fastapi import Depends, Request
from redis.asyncio import Redis

from app.api.deps import get_app_settings, get_redis
from app.core.config import Settings
from app.core.errors import TooManyRequestsError
from app.core.logging import get_logger

log = get_logger(__name__)


def client_ip(request: Request, trusted_hops: int) -> str:
    peer = request.client.host if request.client else "unknown"
    if trusted_hops <= 0:
        return peer
    forwarded = [
        p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()
    ]
    if len(forwarded) < trusted_hops:
        return peer
    return forwarded[-trusted_hops]


async def hit(redis: Redis, key: str, window_s: int) -> tuple[int, int]:
    """Counts one request in the current window. Returns (count, seconds until it resets)."""
    now = int(time.time())
    bucket = now // window_s
    full_key = f"rl:{key}:{bucket}"
    pipe = redis.pipeline()
    pipe.incr(full_key)
    pipe.expire(full_key, window_s + 1)
    count, _ = await pipe.execute()
    return int(count), (bucket + 1) * window_s - now


def rate_limit(
    scope: str,
    limit: Callable[[Settings], int],
    window_s: int,
    *,
    skip_suffixes: tuple[str, ...] = (),
) -> Callable[..., Awaitable[None]]:
    """A dependency allowing `limit(settings)` requests per `window_s` per client and scope."""

    async def dependency(
        request: Request,
        settings: Annotated[Settings, Depends(get_app_settings)],
        redis: Annotated[Redis, Depends(get_redis)],
    ) -> None:
        if not settings.rate_limit_enabled or request.url.path.endswith(skip_suffixes):
            return
        allowed = limit(settings)
        ip = client_ip(request, settings.trusted_proxy_hops)
        try:
            count, reset_in = await hit(cast(Any, redis), f"{scope}:{ip}", window_s)
        except Exception:
            log.warning("ratelimit.redis_unavailable", scope=scope, exc_info=True)
            return
        if count > allowed:
            log.warning("ratelimit.exceeded", scope=scope, client=ip, limit=allowed)
            raise TooManyRequestsError(
                f"Too many requests: at most {allowed} per {_human(window_s)}. "
                f"Retry in {reset_in}s.",
                retry_after_s=reset_in,
                details={"scope": scope, "limit": allowed, "window_s": window_s},
            )

    return dependency


def _human(window_s: int) -> str:
    return {60: "minute", 3600: "hour"}.get(window_s, f"{window_s}s")


limit_create_run = rate_limit("runs", lambda s: s.rate_limit_runs_per_hour, 3600)
limit_llm = rate_limit("llm", lambda s: s.rate_limit_llm_per_minute, 60)
limit_api = rate_limit("api", lambda s: s.rate_limit_api_per_minute, 60, skip_suffixes=("/stream",))
"""Default for every router except health. The SSE stream is exempt: EventSource reconnects."""
