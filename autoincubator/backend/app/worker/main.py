from typing import Any, ClassVar

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


async def ping(ctx: dict[str, Any]) -> str:
    log.info("worker.ping", job_id=ctx.get("job_id"))
    return "pong"


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)
    log.info("worker.startup")


async def shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker.shutdown")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
