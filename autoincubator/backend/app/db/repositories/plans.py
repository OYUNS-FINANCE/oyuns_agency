"""business_plans."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BusinessPlanRow


async def insert_version(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    idea_id: uuid.UUID | None,
    version: int,
    plan: dict[str, object],
    markdown: str,
) -> bool:
    """Idempotent per (run, version): returns False when that version already exists."""
    inserted = await session.scalar(
        insert(BusinessPlanRow)
        .values(
            id=uuid.uuid4(),
            run_id=run_id,
            user_id=user_id,
            idea_id=idea_id,
            version=version,
            plan=plan,
            markdown=markdown,
        )
        .on_conflict_do_nothing(index_elements=["run_id", "version"])
        .returning(BusinessPlanRow.id)
    )
    return inserted is not None


async def latest(
    session: AsyncSession, run_id: uuid.UUID, user_id: uuid.UUID
) -> BusinessPlanRow | None:
    row: BusinessPlanRow | None = await session.scalar(
        select(BusinessPlanRow)
        .where(BusinessPlanRow.run_id == run_id, BusinessPlanRow.user_id == user_id)
        .order_by(BusinessPlanRow.version.desc())
        .limit(1)
    )
    return row
