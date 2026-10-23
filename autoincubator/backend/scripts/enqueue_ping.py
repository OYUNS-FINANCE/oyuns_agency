"""Enqueue a `ping` job and wait for the worker's result (Phase 0 smoke check)."""

import asyncio
import sys

from arq import create_pool
from arq.connections import RedisSettings

from app.core.config import get_settings


async def main() -> int:
    redis = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        job = await redis.enqueue_job("ping")
        if job is None:
            print("enqueue failed")
            return 1
        result = await job.result(timeout=15)
        print(f"job {job.job_id} -> {result}")
        return 0 if result == "pong" else 1
    finally:
        await redis.aclose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
