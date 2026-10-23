"""ideas and idea_versions."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import and_, select
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
