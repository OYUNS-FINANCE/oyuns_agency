from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_app_settings, get_current_user_id, get_session
from app.api.ratelimit import limit_api, limit_llm
from app.core.config import Settings
from app.core.errors import ERROR_RESPONSES
from app.services import llm_settings as service
from app.services.schemas import (
    LLMCatalog,
    LLMConnectionTest,
    LLMSettingsUpdate,
    LLMSettingsView,
)

router = APIRouter(
    prefix="/incubator/settings/llm", tags=["settings"], dependencies=[Depends(limit_api)]
)

Session = Annotated[AsyncSession, Depends(get_session)]
UserId = Annotated[uuid.UUID, Depends(get_current_user_id)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


@router.get("", response_model=LLMSettingsView, responses=ERROR_RESPONSES)
async def get_llm_settings(
    session: Session, user_id: UserId, settings: AppSettings
) -> LLMSettingsView:
    """The LLM configuration new runs will use. API keys are never returned, only whether
    one is set and its last four characters."""
    return await service.get_view(session, settings, user_id)


@router.put("", response_model=LLMSettingsView, responses=ERROR_RESPONSES)
async def put_llm_settings(
    body: LLMSettingsUpdate, session: Session, user_id: UserId, settings: AppSettings
) -> LLMSettingsView:
    """Saves provider, endpoint, models and (optionally) a new API key. Applies to runs
    started afterwards; runs already executing keep what they started with."""
    result = await service.put(session, settings, user_id, body)
    await session.commit()
    return result


@router.delete("", response_model=LLMSettingsView, responses=ERROR_RESPONSES)
async def reset_llm_settings(
    session: Session, user_id: UserId, settings: AppSettings
) -> LLMSettingsView:
    """Forgets the saved configuration (and keys) so the backend environment decides again."""
    result = await service.reset(session, settings, user_id)
    await session.commit()
    return result


@router.post(
    "/test",
    response_model=LLMConnectionTest,
    responses=ERROR_RESPONSES,
    dependencies=[Depends(limit_llm)],
)
async def test_llm_settings(
    body: LLMSettingsUpdate, session: Session, user_id: UserId, settings: AppSettings
) -> LLMConnectionTest:
    """Makes one tiny real call with the submitted configuration, without saving it."""
    return await service.test_connection(session, settings, user_id, body)


@router.get("/catalog", response_model=LLMCatalog, responses=ERROR_RESPONSES)
async def llm_catalog() -> LLMCatalog:
    """Models with known prices, and the per-provider presets."""
    return service.catalog()
