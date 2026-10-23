"""The fixed-window counter against a real Redis."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from redis.asyncio import Redis

from app.api.ratelimit import hit
from app.core.config import get_settings

pytestmark = pytest.mark.integration


async def test_counts_within_a_window_and_expires_the_key() -> None:
    redis = Redis.from_url(get_settings().redis_url)
    key = f"test:{uuid.uuid4().hex}"
    try:
        counts = [(await hit(redis, key, 60))[0] for _ in range(3)]
        count, reset_in = await hit(redis, key, 60)
        assert counts == [1, 2, 3] and count == 4
        assert 0 < reset_in <= 60
        keys = [k async for k in redis.scan_iter(f"rl:{key}:*")]
        assert len(keys) == 1 and 0 < await redis.ttl(keys[0]) <= 61
        # concurrent hits never lose an increment
        results = await asyncio.gather(*(hit(redis, key, 60) for _ in range(20)))
        assert sorted(c for c, _ in results)[-1] == 24
    finally:
        async for k in redis.scan_iter(f"rl:{key}:*"):
            await redis.delete(k)
        await redis.aclose()
