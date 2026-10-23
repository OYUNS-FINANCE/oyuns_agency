from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.common.schemas import FounderProfile
from app.api.deps import get_current_user_id, get_session
from app.core.errors import ERROR_RESPONSES
from app.services import profile as profile_service
from app.services.schemas import ProfileResponse

router = APIRouter(prefix="/incubator", tags=["profile"])

Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]


@router.get("/profile", response_model=ProfileResponse, responses=ERROR_RESPONSES)
async def get_profile(session: Session, user_id: UserId) -> ProfileResponse:
    """The saved founder profile, or defaults (`updated_at: null`) if none was saved."""
    return await profile_service.get_profile(session, user_id)


@router.put("/profile", response_model=ProfileResponse, responses=ERROR_RESPONSES)
async def put_profile(body: FounderProfile, session: Session, user_id: UserId) -> ProfileResponse:
    """Replaces the founder profile. Mode B runs snapshot it when they are created."""
    result = await profile_service.put_profile(session, user_id, body)
    await session.commit()
    return result
