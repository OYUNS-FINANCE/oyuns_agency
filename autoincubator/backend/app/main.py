from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from arq.connections import ArqRedis
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.api import health, profile, runs
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import create_engine, create_sessionmaker
from app.events.broker import EventBroker
from app.events.schema import EVENT_ADAPTER

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    # ArqRedis is a redis.asyncio.Redis that can also enqueue jobs; connects lazily.
    redis: ArqRedis = ArqRedis.from_url(settings.redis_url)
    broker = EventBroker(settings.asyncpg_dsn)
    await broker.start()
    app.state.engine = engine
    app.state.sessionmaker = create_sessionmaker(engine)
    app.state.redis = redis
    app.state.event_broker = broker
    log.info("app.startup", env=settings.app_env)
    try:
        yield
    finally:
        await broker.stop()
        await redis.aclose()
        await engine.dispose()
        log.info("app.shutdown")


def _openapi_with_events(app: FastAPI) -> dict[str, Any]:
    """The default schema plus the SSE `Event` union under components/schemas/Event, which
    the stream route's `data` field references (SSE items are not FastAPI models)."""
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        event = EVENT_ADAPTER.json_schema(
            mode="serialization", ref_template="#/components/schemas/{model}"
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        components.update(event.pop("$defs"))
        components["Event"] = event
        app.openapi_schema = schema
    return app.openapi_schema


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="AutoIncubator", version="0.2.0", lifespan=lifespan)
    install_error_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(profile.router, prefix="/api")
    app.openapi = lambda: _openapi_with_events(app)  # type: ignore[method-assign]
    return app


app = create_app()
