"""In-memory stand-ins for infrastructure clients."""

from __future__ import annotations

from typing import Any


class FakePipeline:
    def __init__(self, redis: FakeRedis):
        self.redis = redis
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    def incr(self, key: str) -> FakePipeline:
        self.ops.append(("incr", (key,)))
        return self

    def expire(self, key: str, seconds: int) -> FakePipeline:
        self.ops.append(("expire", (key, seconds)))
        return self

    async def execute(self) -> list[Any]:
        out: list[Any] = []
        for op, args in self.ops:
            if op == "incr":
                self.redis.counts[args[0]] = self.redis.counts.get(args[0], 0) + 1
                out.append(self.redis.counts[args[0]])
            else:
                self.redis.ttls[args[0]] = args[1]
                out.append(True)
        return out


class FakeRedis:
    """Just the commands the rate limiter uses (INCR + EXPIRE in a pipeline)."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self) -> FakePipeline:
        return FakePipeline(self)


class BrokenRedis:
    def pipeline(self) -> FakePipeline:
        raise ConnectionError("redis is down")
