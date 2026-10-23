from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    get_app_settings,
    get_arq,
    get_broker,
    get_current_user_id,
    get_session,
    get_sessionmaker,
)
from app.core.config import Settings
from app.core.errors import ERROR_RESPONSES
from app.core.logging import get_logger
from app.db.enums import TERMINAL_STATUSES, RunStatus
from app.db.repositories import events as events_repo
from app.db.repositories import runs as runs_repo
from app.events.broker import EventBroker
from app.services import runs as runs_service
from app.services.runs import START_RUN
from app.services.schemas import CreateRunRequest, CreateRunResponse, RunDetail, RunList

router = APIRouter(prefix="/incubator", tags=["runs"])
log = get_logger(__name__)

STREAM_BATCH = 500
SSE_RETRY_MS = 3_000

Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


@router.post(
    "/runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CreateRunResponse,
    responses=ERROR_RESPONSES,
)
async def create_run(
    body: CreateRunRequest,
    session: Session,
    user_id: UserId,
    settings: AppSettings,
    arq: Annotated[ArqRedis, Depends(get_arq)],
) -> CreateRunResponse:
    """Queues a run; the worker executes it. Progress arrives on `/runs/{id}/stream`."""
    run = await runs_service.create_run(session, user_id, body, settings)
    await session.commit()
    try:
        await arq.enqueue_job(
            START_RUN, str(run.id), _job_id=f"start:{run.id}", _queue_name=settings.arq_queue_name
        )
    except Exception:
        # The run row is committed; the worker's recovery sweep enqueues queued runs
        # that have no job, so the run still starts once Redis is back.
        log.warning("runs.enqueue_failed", run_id=str(run.id), exc_info=True)
    return CreateRunResponse(run_id=run.id, status=RunStatus.QUEUED)


@router.get("/runs", response_model=RunList, responses=ERROR_RESPONSES)
async def list_runs(
    session: Session,
    user_id: UserId,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunList:
    return await runs_service.list_runs(session, user_id, limit=limit, offset=offset)


@router.get("/runs/{run_id}", response_model=RunDetail, responses=ERROR_RESPONSES)
async def get_run(run_id: uuid.UUID, session: Session, user_id: UserId) -> RunDetail:
    return await runs_service.run_detail(session, user_id, run_id)


async def _existing_run(
    run_id: uuid.UUID,
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    user_id: UserId,
) -> uuid.UUID:
    """Resolved before the stream starts, so an unknown run is a normal JSON 404. Uses its
    own short session: a request-scoped one would hold a connection for the whole stream."""
    async with sessionmaker() as session:
        await runs_service.get_run(session, user_id, run_id)
    return run_id


def _no_transform(response: Response) -> None:
    """FastAPI sends `no-cache`; `no-transform` also stops proxies from compressing the stream.
    A gzipping proxy (the Next server, by default) would buffer it until the run ends. Set in a
    dependency because a streaming endpoint's body runs after the headers are sent."""
    response.headers["Cache-Control"] = "no-cache, no-transform"


EVENT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "The event id; send back as Last-Event-ID."},
        "retry": {"type": "integer", "minimum": 0},
        "data": {
            "type": "string",
            "contentMediaType": "application/json",
            "contentSchema": {"$ref": "#/components/schemas/Event"},
        },
    },
    "required": ["id", "data"],
}


@router.get(
    "/runs/{run_id}/stream",
    response_class=EventSourceResponse,
    responses=ERROR_RESPONSES,
    dependencies=[Depends(_no_transform)],
    openapi_extra={
        "responses": {"200": {"content": {"text/event-stream": {"itemSchema": EVENT_ITEM_SCHEMA}}}}
    },
)
async def stream_run(
    request: Request,
    run_id: Annotated[uuid.UUID, Depends(_existing_run)],
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    broker: Annotated[EventBroker, Depends(get_broker)],
    settings: AppSettings,
    last_event_id_header: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
    last_event_id: Annotated[
        int | None, Query(ge=0, description="Initial cursor; the header wins when both are set.")
    ] = None,
) -> AsyncIterable[ServerSentEvent]:
    """Server-sent events for one run, in order, each with `id:` = the event id.

    Replays every event after `Last-Event-ID` (header, as sent by EventSource on
    reconnect, or `?last_event_id=`), then streams live. Each `data:` is one JSON `Event`
    envelope. Comment pings keep idle connections open. The stream closes once the run is
    `completed`, `failed` or `budget_exhausted` and every event has been sent.
    """
    cursor = last_event_id_header if last_event_id_header is not None else (last_event_id or 0)
    first = True
    async with broker.subscribe(str(run_id)) as wake:
        while True:
            wake.clear()
            async with sessionmaker() as session:
                # Status first: if it is terminal here, its event is already committed and
                # will be in the batch read below.
                run = await runs_repo.get_any(session, run_id)
                batch = await events_repo.list_after(session, run_id, cursor, STREAM_BATCH)
            for event in batch:
                yield ServerSentEvent(
                    id=str(event.id),
                    raw_data=event.model_dump_json(),
                    retry=SSE_RETRY_MS if first else None,
                )
                first = False
                cursor = event.id
            if len(batch) == STREAM_BATCH:
                continue
            if run is None or run.status in TERMINAL_STATUSES:
                return
            if await request.is_disconnected():
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(wake.wait(), timeout=settings.sse_poll_interval_s)
