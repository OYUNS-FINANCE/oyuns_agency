from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from arq.connections import ArqRedis
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.api import cowork, health, plans, profile, runs
from app.api.middleware import RequestContextMiddleware
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, get_logger
from app.core.telemetry import setup_sentry, setup_tracing, shutdown_tracing
from app.db.session import create_engine, create_sessionmaker
from app.events.broker import EventBroker
from app.events.schema import EVENT_ADAPTER
from app.providers.search.factory import aclose_shared_clients
from app.services.cowork_chat import ChatTasks
from app.services.schemas import CoworkDelta, CoworkFailed, CoworkStarted

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
    app.state.chat_tasks = chat_tasks = ChatTasks()
    log.info("app.startup", env=settings.app_env)
    try:
        yield
    finally:
        await chat_tasks.shutdown()
        await aclose_shared_clients()
        await broker.stop()
        await redis.aclose()
        await engine.dispose()
        log.info("app.shutdown")
        shutdown_tracing()


CHAT_STREAM_MODELS = (CoworkStarted, CoworkDelta, CoworkFailed)
"""Payloads of the co-working reply stream; like SSE events, not FastAPI response models."""


def _openapi_with_events(app: FastAPI) -> dict[str, Any]:
    """The default schema plus the SSE payloads, which stream routes reference but FastAPI
    does not collect: the `Event` union (components/schemas/Event) and the chat events."""
    if app.openapi_schema is None:
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        ref = "#/components/schemas/{model}"
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        event = EVENT_ADAPTER.json_schema(mode="serialization", ref_template=ref)
        components.update(event.pop("$defs"))
        components["Event"] = event
        for model in CHAT_STREAM_MODELS:
            model_schema = model.model_json_schema(mode="serialization", ref_template=ref)
            components.update(model_schema.pop("$defs", {}))
            components[model.__name__] = model_schema
        app.openapi_schema = schema
    return app.openapi_schema


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, service="api")
    setup_sentry(settings, "api")
    tracing = setup_tracing(settings, "api")
    log.info("app.tracing", enabled=tracing)
    app = FastAPI(title="AutoIncubator", version="0.4.0", lifespan=lifespan)
    install_error_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(cowork.router, prefix="/api")
    app.include_router(profile.router, prefix="/api")
    app.include_router(plans.router, prefix="/api")
    app.openapi = lambda: _openapi_with_events(app)  # type: ignore[method-assign]
    return app


app = create_app()
