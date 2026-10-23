"""ideas and idea_versions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.common.brief import IdeaBrief
from app.db.enums import IdeaStatus, IdeaVersionSource
from app.db.models import Idea, IdeaVersion


async def upsert_from_brief(
    session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID, brief: IdeaBrief
) -> tuple[uuid.UUID, bool]:
    """Creates the idea and its version 1 from a ranked brief. Idempotent per (run, key):
    returns (idea id, created?) so a replay does not announce the idea twice."""
    score = Decimal(str(brief.composite_score))
    idea_id = await session.scalar(
        insert(Idea)
        .values(
            id=uuid.uuid4(),
            run_id=run_id,
            user_id=user_id,
            key=brief.idea_id,
            status=IdeaStatus.ACTIVE,
            rank=brief.rank,
            composite_score=score,
            current_version=1,
        )
        .on_conflict_do_nothing(index_elements=["run_id", "key"])
        .returning(Idea.id)
    )
    if idea_id is None:
        existing = await session.scalar(
            select(Idea.id).where(Idea.run_id == run_id, Idea.key == brief.idea_id)
        )
        assert existing is not None
        return existing, False
    session.add(
        IdeaVersion(
            id=uuid.uuid4(),
            idea_id=idea_id,
            user_id=user_id,
            version=1,
            source=IdeaVersionSource.AGENT,
            opportunity=brief.opportunity.model_dump(mode="json"),
            analysis=brief.analysis.model_dump(mode="json"),
            critique=brief.critique.model_dump(mode="json"),
            composite_score=score,
        )
    )
    return idea_id, True


async def latest_for_run(
    session: AsyncSession, run_id: uuid.UUID
) -> Sequence[tuple[Idea, IdeaVersion]]:
    """Every idea of a run with its current version, best rank first."""
    rows = await session.execute(
        select(Idea, IdeaVersion)
        .join(
            IdeaVersion,
            and_(IdeaVersion.idea_id == Idea.id, IdeaVersion.version == Idea.current_version),
        )
        .where(Idea.run_id == run_id)
        .order_by(Idea.rank.asc().nulls_last(), Idea.key)
    )
    return rows.tuples().all()


async def get_for_update(
    session: AsyncSession, run_id: uuid.UUID, idea_id: uuid.UUID
) -> Idea | None:
    idea: Idea | None = await session.scalar(
        select(Idea)
        .where(Idea.id == idea_id, Idea.run_id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return idea


async def get(session: AsyncSession, run_id: uuid.UUID, idea_id: uuid.UUID) -> Idea | None:
    idea: Idea | None = await session.scalar(
        select(Idea).where(Idea.id == idea_id, Idea.run_id == run_id)
    )
    return idea


async def version(session: AsyncSession, idea_id: uuid.UUID, number: int) -> IdeaVersion | None:
    row: IdeaVersion | None = await session.scalar(
        select(IdeaVersion).where(IdeaVersion.idea_id == idea_id, IdeaVersion.version == number)
    )
    return row


async def versions(session: AsyncSession, idea_id: uuid.UUID) -> Sequence[IdeaVersion]:
    rows = await session.scalars(
        select(IdeaVersion).where(IdeaVersion.idea_id == idea_id).order_by(IdeaVersion.version)
    )
    return rows.all()


async def version_for_message(session: AsyncSession, message_id: uuid.UUID) -> IdeaVersion | None:
    row: IdeaVersion | None = await session.scalar(
        select(IdeaVersion).where(IdeaVersion.message_id == message_id)
    )
    return row


async def add_version(
    session: AsyncSession,
    idea: Idea,
    *,
    source: IdeaVersionSource,
    opportunity: dict[str, Any],
    analysis: dict[str, Any],
    critique: dict[str, Any],
    composite_score: float,
    patch: list[dict[str, Any]] | None = None,
    message_id: uuid.UUID | None = None,
) -> IdeaVersion:
    """Appends the next immutable version and points the idea at it (caller holds the lock)."""
    row = IdeaVersion(
        id=uuid.uuid4(),
        idea_id=idea.id,
        user_id=idea.user_id,
        version=idea.current_version + 1,
        source=source,
        opportunity=opportunity,
        analysis=analysis,
        critique=critique,
        composite_score=Decimal(str(composite_score)),
        patch=patch,
        message_id=message_id,
    )
    session.add(row)
    idea.current_version = row.version
    idea.composite_score = row.composite_score
    await session.flush()
    return row


async def rerank(session: AsyncSession, run_id: uuid.UUID) -> None:
    """Ranks the run's live ideas by composite score (best first, key breaks ties); rejected
    ideas lose their rank. Pure Python ordering, like the graph's rank node."""
    rows = (await session.scalars(select(Idea).where(Idea.run_id == run_id))).all()
    live = sorted(
        (i for i in rows if i.status != IdeaStatus.REJECTED),
        key=lambda i: (-(i.composite_score or Decimal(0)), i.key),
    )
    for rank, idea in enumerate(live, start=1):
        idea.rank = rank
    for idea in rows:
        if idea.status == IdeaStatus.REJECTED:
            idea.rank = None
    await session.flush()


MERGE_KEY_PREFIX = "mrg-"


async def next_merge_key(session: AsyncSession, run_id: uuid.UUID) -> str:
    keys = await session.scalars(
        select(Idea.key).where(Idea.run_id == run_id, Idea.key.startswith(MERGE_KEY_PREFIX))
    )
    return f"{MERGE_KEY_PREFIX}{len(keys.all()) + 1:02d}"


async def create_merged(
    session: AsyncSession,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    key: str,
    merged_from: list[uuid.UUID],
    opportunity: dict[str, Any],
    analysis: dict[str, Any],
    critique: dict[str, Any],
    composite_score: float,
) -> Idea:
    score = Decimal(str(composite_score))
    idea = Idea(
        id=uuid.uuid4(),
        run_id=run_id,
        user_id=user_id,
        key=key,
        status=IdeaStatus.ACTIVE,
        composite_score=score,
        current_version=1,
        merged_from=[str(i) for i in merged_from],
    )
    session.add(idea)
    await session.flush()
    session.add(
        IdeaVersion(
            id=uuid.uuid4(),
            idea_id=idea.id,
            user_id=user_id,
            version=1,
            source=IdeaVersionSource.MERGE,
            opportunity=opportunity,
            analysis=analysis,
            critique=critique,
            composite_score=score,
        )
    )
    await session.flush()
    return idea


async def clear_selection(session: AsyncSession, run_id: uuid.UUID) -> None:
    await session.execute(
        update(Idea)
        .where(Idea.run_id == run_id, Idea.status == IdeaStatus.SELECTED)
        .values(status=IdeaStatus.ACTIVE)
    )
