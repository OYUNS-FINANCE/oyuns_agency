from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis

from app.api import health
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import create_engine, create_sessionmaker

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    redis: Redis = Redis.from_url(settings.redis_url)
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = redis
    log.info("app.startup", env=settings.app_env)
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()
        log.info("app.shutdown")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="AutoIncubator", lifespan=lifespan)
    app.include_router(health.router, prefix="/api")
    return app


app = create_app()
