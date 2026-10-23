from collections.abc import AsyncIterator
from typing import cast

from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


def get_engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.engine)


def get_redis(request: Request) -> "Redis":
    return cast("Redis", request.app.state.redis)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    sessionmaker = cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)
    async with sessionmaker() as session:
        yield session
