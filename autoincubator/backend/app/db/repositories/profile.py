"""founder_profile: one row per user."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.common.schemas import FounderProfile
from app.db.enums import RiskTolerance
from app.db.models import FounderProfileRow


def _to_schema(row: FounderProfileRow) -> FounderProfile:
    return FounderProfile(
        skills=list(row.skills),
        region=row.region,
        capital_usd=float(row.capital_usd) if row.capital_usd is not None else None,
        risk_tolerance=row.risk_tolerance.value,
        weekly_hours=row.weekly_hours,
        rejected_idea_reasons=list(row.rejected_idea_reasons),
    )


async def get(session: AsyncSession, user_id: uuid.UUID) -> tuple[FounderProfile, datetime] | None:
    row = await session.get(FounderProfileRow, user_id)
    return None if row is None else (_to_schema(row), row.updated_at)


async def upsert(
    session: AsyncSession, user_id: uuid.UUID, profile: FounderProfile
) -> tuple[FounderProfile, datetime]:
    values = {
        "skills": profile.skills,
        "region": profile.region,
        "capital_usd": Decimal(str(profile.capital_usd))
        if profile.capital_usd is not None
        else None,
        "risk_tolerance": RiskTolerance(profile.risk_tolerance),
        "weekly_hours": profile.weekly_hours,
        "rejected_idea_reasons": profile.rejected_idea_reasons,
    }
    await session.execute(
        insert(FounderProfileRow)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(
            index_elements=["user_id"], set_={**values, "updated_at": func.now()}
        )
    )
    row = await session.scalar(
        select(FounderProfileRow)
        .where(FounderProfileRow.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return _to_schema(row), row.updated_at


async def append_rejected_reason(
    session: AsyncSession, user_id: uuid.UUID, reason: str, keep: int
) -> list[str]:
    """Adds a reason (newest last, keeping the latest `keep`), creating a default profile
    when the founder never saved one. Returns the stored list."""
    await session.execute(
        insert(FounderProfileRow)
        .values(user_id=user_id, risk_tolerance=RiskTolerance.MEDIUM)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    row = await session.scalar(
        select(FounderProfileRow)
        .where(FounderProfileRow.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    row.rejected_idea_reasons = [*row.rejected_idea_reasons, reason][-keep:]
    await session.flush()
    return list(row.rejected_idea_reasons)
