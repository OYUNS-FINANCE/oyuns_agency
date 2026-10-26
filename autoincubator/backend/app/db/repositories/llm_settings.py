"""llm_settings: one row per user."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LLMSettingsRow


async def get(session: AsyncSession, user_id: uuid.UUID) -> LLMSettingsRow | None:
    return await session.get(LLMSettingsRow, user_id)


async def upsert(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    provider: str,
    base_url: str | None,
    anthropic_api_key_enc: str | None,
    openai_api_key_enc: str | None,
    models: dict[str, str],
) -> LLMSettingsRow:
    values = {
        "provider": provider,
        "base_url": base_url,
        "anthropic_api_key_enc": anthropic_api_key_enc,
        "openai_api_key_enc": openai_api_key_enc,
        "models": models,
    }
    await session.execute(
        insert(LLMSettingsRow)
        .values(user_id=user_id, **values)
        .on_conflict_do_update(
            index_elements=["user_id"], set_={**values, "updated_at": func.now()}
        )
    )
    row = await session.scalar(
        select(LLMSettingsRow)
        .where(LLMSettingsRow.user_id == user_id)
        .execution_options(populate_existing=True)
    )
    assert row is not None
    return row


async def delete(session: AsyncSession, user_id: uuid.UUID) -> None:
    row = await session.get(LLMSettingsRow, user_id)
    if row is not None:
        await session.delete(row)
