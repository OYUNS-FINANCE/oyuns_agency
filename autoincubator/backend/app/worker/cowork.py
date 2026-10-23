"""Co-working jobs in the worker: re-score an idea, merge ideas (ADR 0006).

They run while the run is paused and never touch the graph or its lease. Agent work is
reported on the run's event stream; the result is written in one transaction that re-checks
the run is still `awaiting_human` (under the run lock), so a run selected meanwhile is
left alone.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.analyst.node import analyse_opportunity
from app.agents.analyst.schemas import MarketAnalysis
from app.agents.common.context import elapsed_ms, render_run_context
from app.agents.common.schemas import RunInput
from app.agents.scout.merge import merge_candidate
from app.agents.scout.schemas import RawOpportunity
from app.agents.skeptic.node import critique_opportunity
from app.agents.skeptic.schemas import CritiqueScorecard
from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.enums import IdeaVersionSource, RunStatus
from app.db.models import Run
from app.db.repositories import events as events_repo
from app.db.repositories import ideas as ideas_repo
from app.db.repositories import runs as runs_repo
from app.events.schema import AgentCompleted, AgentStarted, AgentThought, IdeaCreated, IdeaUpdated
from app.graph.ranking import composite_score
from app.services import cowork as cowork_service
from app.services import ideas as ideas_service
from app.services.budget import BudgetExhaustedError
from app.services.run_deps import run_deps
from app.worker.runs import WorkerRuntime

log = get_logger(__name__)

PENDING_MERGE_KEY = "mrg-new"


async def _paused_run(rt: WorkerRuntime, run_id: uuid.UUID) -> Run | None:
    async with rt.sessionmaker() as session:
        run = await runs_repo.get_any(session, run_id)
    return run if run is not None and run.status == RunStatus.AWAITING_HUMAN else None


async def rescore_idea(rt: WorkerRuntime, run_id: uuid.UUID, idea_id: uuid.UUID) -> str:
    """The Skeptic scores the idea's latest version; the new scorecard becomes a version."""
    run = await _paused_run(rt, run_id)
    if run is None:
        return "skipped"
    async with rt.sessionmaker() as session:
        idea = await ideas_repo.get(session, run.id, idea_id)
        if idea is None:
            return "skipped"
        current = await ideas_repo.version(session, idea.id, idea.current_version)
        assert current is not None
    deps, _ = run_deps(rt.settings, rt.sessionmaker, run)
    started = time.monotonic()
    agent = "skeptic"
    await deps.events.emit(AgentStarted(node="rescore", items=1, idea_id=idea_id), agent=agent)
    brief = ideas_service.editable(current)
    outcome = "failed"
    try:
        critique, _ = await critique_opportunity(
            brief.opportunity,
            brief.analysis,
            render_run_context(RunInput.model_validate(run.input)),
            deps,
        )
    except BudgetExhaustedError as exc:
        critique = None
        await deps.events.emit(AgentThought(text=f"Re-score stopped: {exc}."), agent=agent)
    if critique is not None:
        score = composite_score(critique, rt.settings.rubric_weights)
        async with rt.sessionmaker() as session, session.begin():
            try:
                locked = await cowork_service.lock_paused_run(session, run.user_id, run.id)
                live, latest = await cowork_service.lock_idea(session, run.id, idea_id)
            except AppError as exc:
                log.info("cowork.rescore_dropped", run_id=str(run.id), reason=exc.message)
                live = None
            if live is not None and latest.version != current.version:
                await _note(
                    session,
                    run,
                    agent,
                    "The idea changed while it was being re-scored; re-score it again to "
                    "score the latest version.",
                )
            elif live is not None:
                await ideas_repo.add_version(
                    session,
                    live,
                    source=IdeaVersionSource.RESCORE,
                    opportunity=latest.opportunity,
                    analysis=latest.analysis,
                    critique=critique.model_dump(mode="json"),
                    composite_score=score,
                )
                await ideas_repo.rerank(session, locked.id)
                await events_repo.insert_event(
                    session,
                    run_id=run.id,
                    user_id=run.user_id,
                    data=IdeaUpdated(
                        idea_id=live.id,
                        version=live.current_version,
                        composite_score=score,
                        status=live.status,
                        source=IdeaVersionSource.RESCORE,
                    ),
                )
                outcome = "rescored"
    await deps.events.emit(
        AgentCompleted(
            node="rescore",
            duration_ms=elapsed_ms(started),
            summary={"rescored": int(outcome == "rescored"), "failed": int(outcome != "rescored")},
            idea_id=idea_id,
        ),
        agent=agent,
    )
    return outcome


async def _note(session: AsyncSession, run: Run, agent: str, text: str) -> None:
    """An `agent.thought` written inside the caller's transaction."""
    await events_repo.insert_event(
        session, run_id=run.id, user_id=run.user_id, data=AgentThought(text=text), agent=agent
    )


async def merge_ideas(rt: WorkerRuntime, run_id: uuid.UUID, idea_ids: Sequence[uuid.UUID]) -> str:
    """Scout synthesises a hybrid, then the Analyst and the Skeptic run on it, as for any
    new idea. The sources stay active; the hybrid records `merged_from`."""
    run = await _paused_run(rt, run_id)
    if run is None:
        return "skipped"
    sources: list[RawOpportunity] = []
    async with rt.sessionmaker() as session:
        for idea_id in idea_ids:
            idea = await ideas_repo.get(session, run.id, idea_id)
            if idea is None:
                return "skipped"
            version = await ideas_repo.version(session, idea.id, idea.current_version)
            assert version is not None
            sources.append(RawOpportunity.model_validate(version.opportunity))
    deps, _ = run_deps(rt.settings, rt.sessionmaker, run)
    run_context = render_run_context(RunInput.model_validate(run.input))
    started = time.monotonic()
    created: uuid.UUID | None = None
    await deps.events.emit(AgentStarted(node="merge", items=len(sources)), agent="scout")
    try:
        candidate, _ = await merge_candidate(sources, run_context, deps)
        await deps.events.emit(
            AgentThought(text=f"Merged {len(sources)} ideas into {candidate.title!r}."),
            agent="scout",
        )
        hybrid = RawOpportunity(
            **candidate.model_dump(),
            id=PENDING_MERGE_KEY,
            iteration=max(o.iteration for o in sources),
        )
        analysis, _ = await analyse_opportunity(hybrid, run_context, deps)
        critique = None
        if analysis is not None:
            critique, _ = await critique_opportunity(hybrid, analysis, run_context, deps)
        if analysis is not None and critique is not None:
            created = await _store_merge(rt, run, idea_ids, hybrid, analysis, critique)
        else:
            await deps.events.emit(
                AgentThought(text="The hybrid could not be analysed and scored; nothing stored."),
                agent="scout",
            )
    except BudgetExhaustedError as exc:
        await deps.events.emit(AgentThought(text=f"Merge stopped: {exc}."), agent="scout")
    await deps.events.emit(
        AgentCompleted(
            node="merge",
            duration_ms=elapsed_ms(started),
            summary={"created": int(created is not None), "failed": int(created is None)},
            idea_id=created,
        ),
        agent="scout",
    )
    return "merged" if created is not None else "failed"


async def _store_merge(
    rt: WorkerRuntime,
    run: Run,
    source_ids: Sequence[uuid.UUID],
    hybrid: RawOpportunity,
    analysis: MarketAnalysis,
    critique: CritiqueScorecard,
) -> uuid.UUID | None:
    score = composite_score(critique, rt.settings.rubric_weights)
    async with rt.sessionmaker() as session, session.begin():
        try:
            await cowork_service.lock_paused_run(session, run.user_id, run.id)
        except AppError as exc:
            log.info("cowork.merge_dropped", run_id=str(run.id), reason=exc.message)
            return None
        # The key is drawn under the run lock, so concurrent merges never collide.
        key = await ideas_repo.next_merge_key(session, run.id)
        idea = await ideas_repo.create_merged(
            session,
            run.id,
            run.user_id,
            key=key,
            merged_from=list(source_ids),
            opportunity=hybrid.model_copy(update={"id": key}).model_dump(mode="json"),
            analysis=analysis.model_copy(update={"opportunity_id": key}).model_dump(mode="json"),
            critique=critique.model_copy(update={"opportunity_id": key}).model_dump(mode="json"),
            composite_score=score,
        )
        await ideas_repo.rerank(session, run.id)
        await events_repo.insert_event(
            session,
            run_id=run.id,
            user_id=run.user_id,
            data=IdeaCreated(
                idea_id=idea.id,
                key=key,
                title=hybrid.title,
                rank=idea.rank,
                composite_score=score,
                version=1,
            ),
        )
        return idea.id
