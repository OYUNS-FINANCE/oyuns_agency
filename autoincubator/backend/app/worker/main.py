import os
import socket
import uuid
from typing import Any, ClassVar

from arq import cron, func
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import create_engine, create_sessionmaker
from app.worker import cowork as cowork_jobs
from app.worker.runs import WorkerRuntime, execute_run, recover_stale_runs

log = get_logger(__name__)
settings = get_settings()

RECOVERY_SECONDS = {0, 15, 30, 45}


async def ping(ctx: dict[str, Any]) -> str:
    log.info("worker.ping", job_id=ctx.get("job_id"))
    return "pong"


async def start_run(ctx: dict[str, Any], run_id: str) -> str:
    rt: WorkerRuntime = ctx["runtime"]
    return await execute_run(rt, uuid.UUID(run_id), str(ctx["job_id"]))


async def rescore_idea(ctx: dict[str, Any], run_id: str, idea_id: str) -> str:
    rt: WorkerRuntime = ctx["runtime"]
    return await cowork_jobs.rescore_idea(rt, uuid.UUID(run_id), uuid.UUID(idea_id))


async def merge_ideas(ctx: dict[str, Any], run_id: str, idea_ids: list[str]) -> str:
    rt: WorkerRuntime = ctx["runtime"]
    return await cowork_jobs.merge_ideas(rt, uuid.UUID(run_id), [uuid.UUID(i) for i in idea_ids])


async def recover_runs(ctx: dict[str, Any]) -> int:
    rt: WorkerRuntime = ctx["runtime"]
    return len(await recover_stale_runs(rt, ctx["redis"].enqueue_job))


async def startup(ctx: dict[str, Any]) -> None:
    s = get_settings()
    configure_logging(s.log_level)
    engine = create_engine(s.database_url)
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:6]}"
    ctx["runtime"] = WorkerRuntime(
        settings=s, engine=engine, sessionmaker=create_sessionmaker(engine), worker_id=worker_id
    )
    log.info("worker.startup", worker_id=worker_id, queue=s.arq_queue_name)


async def shutdown(ctx: dict[str, Any]) -> None:
    rt: WorkerRuntime | None = ctx.get("runtime")
    if rt is not None:
        await rt.engine.dispose()
    log.info("worker.shutdown")


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        ping,
        func(start_run, timeout=settings.run_job_timeout_s, max_tries=3),
        # Co-working jobs are not retried: a partial retry would charge the budget twice,
        # and the founder can simply ask again.
        func(rescore_idea, timeout=600, max_tries=1),
        func(merge_ideas, timeout=900, max_tries=1),
    ]
    cron_jobs: ClassVar[list[Any]] = [
        # Also at startup, so a restarted worker picks up runs its predecessor dropped.
        cron(recover_runs, second=RECOVERY_SECONDS, run_at_startup=True, timeout=60)
    ]
    on_startup = startup
    on_shutdown = shutdown
    queue_name = settings.arq_queue_name
    job_timeout = settings.run_job_timeout_s
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
