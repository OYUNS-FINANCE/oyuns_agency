"""Saved LLM configuration against Postgres: round trip, key masking, per-run resolution."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
from pydantic import SecretStr
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import MODEL_PRESETS, Settings, get_settings
from app.db.models import LLMSettingsRow
from app.db.session import create_engine, create_sessionmaker
from app.services import llm_settings as service
from app.services.schemas import AgentModels, LLMSettingsUpdate

pytestmark = pytest.mark.integration

USER = uuid.uuid4()


@pytest.fixture
async def sm() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(get_settings().database_url)
    sessionmaker = create_sessionmaker(engine)
    try:
        yield sessionmaker
    finally:
        async with sessionmaker() as session, session.begin():
            await session.execute(delete(LLMSettingsRow).where(LLMSettingsRow.user_id == USER))
        await engine.dispose()


async def test_save_mask_keep_clear_and_resolve(sm: async_sessionmaker[AsyncSession]) -> None:
    base = Settings(_env_file=None, app_env="test", llm_provider="fake")
    models = AgentModels(**MODEL_PRESETS["anthropic"])
    async with sm() as session, session.begin():
        view = await service.put(
            session,
            base,
            USER,
            LLMSettingsUpdate(
                provider="anthropic", models=models, api_key=SecretStr("sk-ant-secret-WXYZ")
            ),
        )
    assert view.source == "ui" and view.anthropic_key.hint == "WXYZ"
    assert "secret" not in view.model_dump_json()

    async with sm() as session:
        row = await session.get(LLMSettingsRow, USER)
        assert row is not None and "secret" not in (row.anthropic_api_key_enc or "")

    # Saving again without a key keeps the stored one.
    async with sm() as session, session.begin():
        view = await service.put(
            session, base, USER, LLMSettingsUpdate(provider="anthropic", models=models)
        )
    assert view.anthropic_key.is_set

    eff = await service.effective_settings(sm, base, USER)
    assert eff.llm_provider == "anthropic"
    assert eff.anthropic_api_key is not None
    assert eff.anthropic_api_key.get_secret_value() == "sk-ant-secret-WXYZ"
    assert base.llm_provider == "fake"

    async with sm() as session, session.begin():
        view = await service.put(
            session,
            base,
            USER,
            LLMSettingsUpdate(provider="anthropic", models=models, clear_api_key=True),
        )
    assert not view.anthropic_key.is_set

    async with sm() as session, session.begin():
        view = await service.reset(session, base, USER)
    assert view.source == "environment"
    assert (await service.effective_settings(sm, base, USER)).llm_provider == "fake"
