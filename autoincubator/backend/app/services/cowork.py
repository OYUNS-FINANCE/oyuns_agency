"""Co-working while the run is paused at the checkpoint (ADR 0006).

Every mutating action row-locks the run (then the idea) and is refused with 409 unless the
run is `awaiting_human`. Versions are immutable rows; scores and ranks are recomputed in
Python. Select moves the run back to `running` exactly once; the worker then resumes the
graph with the selected idea's latest version.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.db.enums import CoworkMessageState, CoworkRole, IdeaStatus, IdeaVersionSource, RunStatus
from app.db.models import CoworkMessage, Idea, IdeaVersion, Run
from app.db.repositories import cowork as cowork_repo
from app.db.repositories import events as events_repo
from app.db.repositories import ideas as ideas_repo
from app.db.repositories import profile as profile_repo
from app.db.repositories import runs as runs_repo
from app.events.schema import IdeaUpdated, RunResumed
from app.services import ideas as ideas_service
from app.services import runs as runs_service
from app.services.brief_patch import PatchError, PatchOperation, apply_patch
from app.services.schemas import (
    CoworkMessageList,
    CoworkMessageView,
    IdeaDetail,
    IdeaView,
    SelectResponse,
)

RESCORE_IDEA = "rescore_idea"
MERGE_IDEAS = "merge_ideas"
"""arq job names of the worker's co-working tasks."""
RESUME_JOB_PREFIX = "resume:"


# --- Guards -------------------------------------------------------------------------------


async def lock_paused_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = await runs_repo.get_for_update(session, run_id, user_id)
    if run is None:
        raise NotFoundError(f"run {run_id} not found")
    if run.status != RunStatus.AWAITING_HUMAN:
        raise ConflictError(
            f"run {run_id} is {run.status.value}; co-working is only possible while it is "
            "paused for review (awaiting_human)",
            code="run_not_paused",
            details={"status": run.status.value},
        )
    return run


def check_budget(run: Run, *, searches: bool = False) -> None:
    """Co-working calls are charged to the run's budget. An exhausted budget refuses the
    call but leaves the run paused, so the founder can still select (ADR 0006)."""
    if run.tokens_used >= run.max_tokens or (searches and run.searches_used >= run.max_searches):
        raise ConflictError(
            "the run's budget is exhausted; co-working calls are no longer possible",
            code="budget_exhausted",
            details={
                "tokens_used": run.tokens_used,
                "max_tokens": run.max_tokens,
                "searches_used": run.searches_used,
                "max_searches": run.max_searches,
            },
        )


async def lock_idea(
    session: AsyncSession, run_id: uuid.UUID, idea_id: uuid.UUID, *, active: bool = True
) -> tuple[Idea, IdeaVersion]:
    idea = await ideas_repo.get_for_update(session, run_id, idea_id)
    if idea is None:
        raise NotFoundError(f"idea {idea_id} not found in run {run_id}")
    if active and idea.status != IdeaStatus.ACTIVE:
        raise ConflictError(f"idea {idea_id} is {idea.status.value}", code="idea_not_active")
    version = await ideas_repo.version(session, idea.id, idea.current_version)
    assert version is not None
    return idea, version


# --- Reads --------------------------------------------------------------------------------


async def _readable_idea(
    session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID, idea_id: uuid.UUID
) -> Idea:
    await runs_service.get_run(session, user_id, run_id)
    idea = await ideas_repo.get(session, run_id, idea_id)
    if idea is None:
        raise NotFoundError(f"idea {idea_id} not found in run {run_id}")
    return idea


async def idea_detail(
    session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID, idea_id: uuid.UUID
) -> IdeaDetail:
    idea = await _readable_idea(session, user_id, run_id, idea_id)
    versions = await ideas_repo.versions(session, idea.id)
    return IdeaDetail(
        idea=ideas_service.to_view(idea, versions[-1]),
        versions=[ideas_service.to_version_view(v) for v in versions],
    )


async def _message_views(
    session: AsyncSession, messages: Sequence[CoworkMessage], settings: Settings
) -> list[CoworkMessageView]:
    applied = (
        {
            v.message_id: v.version
            for v in await ideas_repo.versions(session, messages[0].idea_id)
            if v.message_id is not None
        }
        if messages
        else {}
    )
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.cowork_reply_timeout_s)
    return [
        ideas_service.to_message_view(m, applied.get(m.id), stale=m.created_at < cutoff)
        for m in messages
    ]


async def list_messages(
    session: AsyncSession,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    idea_id: uuid.UUID,
    settings: Settings,
) -> CoworkMessageList:
    idea = await _readable_idea(session, user_id, run_id, idea_id)
    messages = await cowork_repo.for_idea(session, idea.id)
    return CoworkMessageList(items=await _message_views(session, messages, settings))


async def message_view(
    session: AsyncSession, message: CoworkMessage, settings: Settings
) -> CoworkMessageView:
    return (await _message_views(session, [message], settings))[0]


# --- Writes -------------------------------------------------------------------------------


async def _announce(
    session: AsyncSession,
    run: Run,
    idea: Idea,
    *,
    source: IdeaVersionSource | None = None,
) -> None:
    await events_repo.insert_event(
        session,
        run_id=run.id,
        user_id=run.user_id,
        data=IdeaUpdated(
            idea_id=idea.id,
            version=idea.current_version,
            composite_score=float(idea.composite_score)
            if idea.composite_score is not None
            else None,
            status=idea.status,
            source=source,
        ),
    )


async def _latest_view(session: AsyncSession, idea: Idea) -> IdeaView:
    version = await ideas_repo.version(session, idea.id, idea.current_version)
    assert version is not None
    return ideas_service.to_view(idea, version)


async def apply_version(
    session: AsyncSession,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    idea_id: uuid.UUID,
    message_id: uuid.UUID,
) -> tuple[IdeaView, bool]:
    """Turns a proposed patch into the idea's next version. Applying the same proposal again
    returns the version it already produced (False = nothing new was created)."""
    run = await lock_paused_run(session, user_id, run_id)
    idea, current = await lock_idea(session, run.id, idea_id)
    message = await cowork_repo.get(session, idea.id, message_id)
    if message is None or message.role != CoworkRole.ASSISTANT:
        raise NotFoundError(f"message {message_id} is not an agent reply on idea {idea_id}")
    if await ideas_repo.version_for_message(session, message.id) is not None:
        return await _latest_view(session, idea), False
    if message.state != CoworkMessageState.COMPLETE or not message.proposed_patch:
        raise ConflictError(
            f"message {message_id} has no proposed change to apply", code="no_proposed_patch"
        )
    ops = [PatchOperation.model_validate(op) for op in message.proposed_patch]
    try:
        patched = apply_patch(ideas_service.editable(current), ops)
    except PatchError as exc:
        # Proposed against an older version that has changed since.
        raise ConflictError(
            f"the proposed change no longer applies to version {current.version}: {exc}",
            code="patch_conflict",
            details={"based_on_version": message.based_on_version},
        ) from exc
    await ideas_repo.add_version(
        session,
        idea,
        source=IdeaVersionSource.COWORK,
        opportunity=patched.opportunity.model_dump(mode="json"),
        analysis=patched.analysis.model_dump(mode="json"),
        critique=current.critique,
        composite_score=float(current.composite_score),
        patch=[op.model_dump(mode="json") for op in ops],
        message_id=message.id,
    )
    await _announce(session, run, idea, source=IdeaVersionSource.COWORK)
    return await _latest_view(session, idea), True


async def reject(
    session: AsyncSession,
    user_id: uuid.UUID,
    run_id: uuid.UUID,
    idea_id: uuid.UUID,
    reason: str | None,
    settings: Settings,
) -> IdeaView:
    """Marks the idea rejected. A reason is also kept in the founder profile, which Mode B
    runs snapshot and show to the Scout as ideas to steer away from."""
    run = await lock_paused_run(session, user_id, run_id)
    idea, current = await lock_idea(session, run.id, idea_id)
    reason = (reason or "").strip() or None
    idea.status = IdeaStatus.REJECTED
    idea.reject_reason = reason
    if reason:
        title = str(current.opportunity["title"])
        await profile_repo.append_rejected_reason(
            session, run.user_id, f"{title}: {reason}", settings.rejected_reasons_max
        )
    await ideas_repo.rerank(session, run.id)
    await _announce(session, run, idea)
    return await _latest_view(session, idea)


async def check_rescore(
    session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID, idea_id: uuid.UUID
) -> int:
    """Validates a re-score request; returns the version the worker will score."""
    run = await lock_paused_run(session, user_id, run_id)
    check_budget(run)
    idea, _ = await lock_idea(session, run.id, idea_id)
    return idea.current_version


async def check_merge(
    session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID, idea_ids: Sequence[uuid.UUID]
) -> None:
    run = await lock_paused_run(session, user_id, run_id)
    check_budget(run, searches=True)
    for idea_id in sorted(idea_ids):  # a fixed lock order
        await lock_idea(session, run.id, idea_id)


async def select(
    session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID, idea_id: uuid.UUID
) -> tuple[SelectResponse, bool]:
    """Moves `awaiting_human → running` with the selection, in one transaction under the run
    lock, so concurrent or repeated calls resume at most once. Repeating the same selection
    is idempotent; selecting a different idea once resumed is a conflict. Returns
    (response, True when this call resumed the run and must enqueue the worker job)."""
    run = await runs_repo.get_for_update(session, run_id, user_id)
    if run is None:
        raise NotFoundError(f"run {run_id} not found")
    if run.status != RunStatus.AWAITING_HUMAN:
        if run.selected_idea_id == idea_id:
            return SelectResponse(run_id=run.id, status=run.status, selected_idea_id=idea_id), False
        raise ConflictError(
            f"run {run_id} is {run.status.value} and cannot be resumed with this idea",
            code="run_not_paused",
            details={"status": run.status.value, "selected_idea_id": run.selected_idea_id},
        )
    idea, _ = await lock_idea(session, run.id, idea_id)
    idea.status = IdeaStatus.SELECTED
    await _announce(session, run, idea)
    await events_repo.insert_event(
        session, run_id=run.id, user_id=run.user_id, data=RunResumed(selected_idea_id=idea.id)
    )
    moved = await runs_service.transition(
        session,
        run.id,
        run.user_id,
        RunStatus.RUNNING,
        detail="Developing the selected idea into a business plan.",
        values={"selected_idea_id": idea.id},
        only_from=[RunStatus.AWAITING_HUMAN],
    )
    assert moved, "the run row is locked and was awaiting_human"
    return SelectResponse(run_id=run.id, status=RunStatus.RUNNING, selected_idea_id=idea.id), True
