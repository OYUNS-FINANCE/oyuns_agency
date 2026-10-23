"""Co-working at the checkpoint (ADR 0006). Mutations return 409 unless the run is
`awaiting_human`; reads work in any status."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterable, AsyncIterator
from typing import Annotated, cast

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    get_app_settings,
    get_arq,
    get_current_user_id,
    get_session,
    get_sessionmaker,
    no_transform,
)
from app.core.config import Settings
from app.core.errors import CONFLICT_RESPONSES, ERROR_RESPONSES
from app.core.logging import get_logger
from app.services import cowork as cowork_service
from app.services.cowork import MERGE_IDEAS, RESCORE_IDEA, RESUME_JOB_PREFIX
from app.services.cowork_chat import ChatEvent, ChatTasks, start_chat
from app.services.runs import START_RUN
from app.services.schemas import (
    ApplyVersionRequest,
    CoworkMessageList,
    CoworkRequest,
    IdeaDetail,
    IdeaView,
    JobAccepted,
    MergeRequest,
    RejectRequest,
    SelectRequest,
    SelectResponse,
)

router = APIRouter(prefix="/incubator/runs/{run_id}", tags=["cowork"])
log = get_logger(__name__)

Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]
Arq = Annotated[ArqRedis, Depends(get_arq)]


async def _enqueue(arq: ArqRedis, settings: Settings, job: str, *args: object, job_id: str) -> None:
    await arq.enqueue_job(job, *args, _job_id=job_id, _queue_name=settings.arq_queue_name)


@router.get("/ideas/{idea_id}", response_model=IdeaDetail, responses=ERROR_RESPONSES)
async def get_idea(
    run_id: uuid.UUID, idea_id: uuid.UUID, session: Session, user_id: UserId
) -> IdeaDetail:
    """The idea at its latest version plus every version (oldest first), for diffs."""
    return await cowork_service.idea_detail(session, user_id, run_id, idea_id)


@router.get("/ideas/{idea_id}/cowork", response_model=CoworkMessageList, responses=ERROR_RESPONSES)
async def list_cowork_messages(
    run_id: uuid.UUID, idea_id: uuid.UUID, session: Session, user_id: UserId, settings: AppSettings
) -> CoworkMessageList:
    """The chat on this idea, oldest first. A reply still being generated is `pending`."""
    return await cowork_service.list_messages(session, user_id, run_id, idea_id, settings)


def _chat_tasks(request: Request) -> ChatTasks:
    return cast(ChatTasks, request.app.state.chat_tasks)


async def _open_chat(
    run_id: uuid.UUID,
    idea_id: uuid.UUID,
    body: CoworkRequest,
    sessionmaker: Annotated[async_sessionmaker[AsyncSession], Depends(get_sessionmaker)],
    settings: AppSettings,
    user_id: UserId,
    tasks: Annotated[ChatTasks, Depends(_chat_tasks)],
) -> AsyncIterator[ChatEvent]:
    """Resolved before the stream starts, so 404/409 are normal JSON errors."""
    return await start_chat(sessionmaker, settings, tasks, user_id, run_id, idea_id, body)


@router.post(
    "/ideas/{idea_id}/cowork",
    response_class=EventSourceResponse,
    responses=CONFLICT_RESPONSES,
    dependencies=[Depends(no_transform)],
    openapi_extra={
        "responses": {
            "200": {
                "description": (
                    "SSE. `started` (CoworkStarted), then `delta` (CoworkDelta) events with "
                    "reply text, `reset` when a retry discards the text so far, and finally "
                    "`completed` (CoworkMessageView) or `error` (CoworkFailed)."
                ),
                "content": {
                    "text/event-stream": {
                        "itemSchema": {
                            "type": "object",
                            "properties": {
                                "event": {
                                    "enum": ["started", "delta", "reset", "completed", "error"]
                                },
                                "data": {"type": "string", "contentMediaType": "application/json"},
                            },
                            "required": ["event", "data"],
                        }
                    }
                },
            }
        }
    },
)
async def cowork(
    stream: Annotated[AsyncIterator[ChatEvent], Depends(_open_chat)],
) -> AsyncIterable[ServerSentEvent]:
    """Chat with one agent about this idea; the reply streams back. The agent may propose a
    change (`proposed_patch` on the completed message), which `POST …/versions` applies.
    The reply is stored even if this connection drops."""
    async for name, payload in stream:
        data = payload.model_dump_json() if isinstance(payload, BaseModel) else "{}"
        yield ServerSentEvent(event=name, raw_data=data)


@router.post(
    "/ideas/{idea_id}/versions",
    response_model=IdeaView,
    responses=CONFLICT_RESPONSES,
    status_code=status.HTTP_201_CREATED,
)
async def apply_version(
    run_id: uuid.UUID,
    idea_id: uuid.UUID,
    body: ApplyVersionRequest,
    session: Session,
    user_id: UserId,
    response: Response,
) -> IdeaView:
    """Applies an agent's proposed patch as the idea's next version (201). The same proposal
    applied again returns that version (200). The score is then stale until re-scored."""
    view, created = await cowork_service.apply_version(
        session, user_id, run_id, idea_id, body.message_id
    )
    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return view


@router.post(
    "/ideas/{idea_id}/rescore",
    response_model=JobAccepted,
    responses=CONFLICT_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
)
async def rescore(
    run_id: uuid.UUID,
    idea_id: uuid.UUID,
    session: Session,
    user_id: UserId,
    settings: AppSettings,
    arq: Arq,
) -> JobAccepted:
    """The Skeptic re-scores the latest version in the worker; `agent.*` and `idea.updated`
    arrive on the run's stream."""
    version = await cowork_service.check_rescore(session, user_id, run_id, idea_id)
    await session.commit()
    job_id = f"rescore:{idea_id}:v{version}:{uuid.uuid4().hex[:8]}"
    await _enqueue(arq, settings, RESCORE_IDEA, str(run_id), str(idea_id), job_id=job_id)
    return JobAccepted(job_id=job_id)


@router.post("/ideas/{idea_id}/reject", response_model=IdeaView, responses=CONFLICT_RESPONSES)
async def reject(
    run_id: uuid.UUID,
    idea_id: uuid.UUID,
    body: RejectRequest,
    session: Session,
    user_id: UserId,
    settings: AppSettings,
) -> IdeaView:
    """Rejects the idea. The reason is kept in the founder profile, so the next Mode B runs
    steer away from it."""
    view = await cowork_service.reject(session, user_id, run_id, idea_id, body.reason, settings)
    await session.commit()
    return view


@router.post(
    "/ideas/merge",
    response_model=JobAccepted,
    responses=CONFLICT_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
)
async def merge(
    run_id: uuid.UUID,
    body: MergeRequest,
    session: Session,
    user_id: UserId,
    settings: AppSettings,
    arq: Arq,
) -> JobAccepted:
    """Merges 2-4 active ideas into a hybrid in the worker: Scout synthesis, then Analyst and
    Skeptic. Progress and the new idea (`idea.created`) arrive on the run's stream."""
    await cowork_service.check_merge(session, user_id, run_id, body.idea_ids)
    await session.commit()
    job_id = f"merge:{run_id}:{uuid.uuid4().hex[:8]}"
    ids = [str(i) for i in body.idea_ids]
    await _enqueue(arq, settings, MERGE_IDEAS, str(run_id), ids, job_id=job_id)
    return JobAccepted(job_id=job_id)


@router.post(
    "/select",
    response_model=SelectResponse,
    responses=CONFLICT_RESPONSES,
    status_code=status.HTTP_202_ACCEPTED,
)
async def select(
    run_id: uuid.UUID,
    body: SelectRequest,
    session: Session,
    user_id: UserId,
    settings: AppSettings,
    arq: Arq,
) -> SelectResponse:
    """Selects the idea to develop and resumes the graph into Phase 2. Idempotent: repeating
    the same selection returns 202 without resuming again; another idea is a 409."""
    result, resumed = await cowork_service.select(session, user_id, run_id, body.idea_id)
    await session.commit()
    if resumed:
        try:
            await _enqueue(
                arq, settings, START_RUN, str(run_id), job_id=f"{RESUME_JOB_PREFIX}{run_id}"
            )
        except Exception:
            # The run is committed as running without a lease: the recovery sweep resumes it.
            log.warning("cowork.resume_enqueue_failed", run_id=str(run_id), exc_info=True)
    return result
