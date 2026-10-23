import uuid
from collections.abc import AsyncIterator
from typing import cast

from arq.connections import ArqRedis
from fastapi import Request
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.events.broker import EventBroker


def get_engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.engine)


def get_redis(request: Request) -> "Redis":
    return cast("Redis", request.app.state.redis)


def get_arq(request: Request) -> ArqRedis:
    return cast(ArqRedis, request.app.state.redis)


def get_sessionmaker(request: Request) -> async_sessionmaker[AsyncSession]:
    return cast(async_sessionmaker[AsyncSession], request.app.state.sessionmaker)


def get_broker(request: Request) -> EventBroker:
    return cast(EventBroker, request.app.state.event_broker)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker(request)() as session:
        yield session


def get_app_settings() -> Settings:
    return get_settings()


def get_current_user_id() -> uuid.UUID:
    """Single-user mode until auth exists: every request acts as DEFAULT_USER_ID."""
    return get_settings().default_user_id
