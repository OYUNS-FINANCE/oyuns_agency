"""Founder profile: read with defaults, replace on PUT."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.common.schemas import FounderProfile
from app.db.repositories import profile as profile_repo
from app.services.schemas import ProfileResponse


async def get_profile(session: AsyncSession, user_id: uuid.UUID) -> ProfileResponse:
    stored = await profile_repo.get(session, user_id)
    if stored is None:
        return ProfileResponse(profile=FounderProfile(), updated_at=None)
    profile, updated_at = stored
    return ProfileResponse(profile=profile, updated_at=updated_at)


async def put_profile(
    session: AsyncSession, user_id: uuid.UUID, profile: FounderProfile
) -> ProfileResponse:
    saved, updated_at = await profile_repo.upsert(session, user_id, profile)
    return ProfileResponse(profile=saved, updated_at=updated_at)
