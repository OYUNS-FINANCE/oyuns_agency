"""LLM provider configuration saved from the UI, layered over the environment (ADR 0010).

A saved row fully specifies provider, endpoint and the seven agent models; API keys fall back
to the environment when none was saved for the provider. Without a row the environment alone
decides, exactly as before.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from urllib.parse import urlparse

import structlog
from pydantic import BaseModel, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import AGENT_MODEL_FIELDS, MODEL_PRESETS, Settings
from app.core.errors import AppError
from app.core.secrets import SecretsError, decrypt, encrypt
from app.db.models import LLMSettingsRow
from app.db.repositories import llm_settings as repo
from app.providers.factory import build_llm
from app.providers.llm.base import ChatMessage, LLMRequest
from app.providers.llm.pricing import PRICES
from app.services.schemas import (
    AgentModels,
    ApiKeyStatus,
    CatalogModel,
    LLMCatalog,
    LLMConnectionTest,
    LLMSettingsUpdate,
    LLMSettingsView,
)

log = structlog.get_logger(__name__)

TEST_TIMEOUT_S = 30.0


class InvalidLLMSettingsError(AppError):
    status_code = 422
    code = "invalid_llm_settings"


def _secret(value: object) -> str:
    return (
        value.get_secret_value() if value is not None and hasattr(value, "get_secret_value") else ""
    )


def _normalise_base_url(raw: str | None) -> str | None:
    url = (raw or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidLLMSettingsError("Base URL must be an http(s) URL, e.g. https://host/v1")
    return url


def _models_from(settings: Settings) -> AgentModels:
    return AgentModels(**{name: getattr(settings, name) for name in AGENT_MODEL_FIELDS})


def _stored_key(settings: Settings, enc: str | None) -> str | None:
    """The decrypted UI key, or None when absent or unreadable."""
    if not enc:
        return None
    try:
        return decrypt(settings, enc)
    except SecretsError as exc:
        log.warning("llm_settings.key_unreadable", error=str(exc))
        return None


def _status(ui_key: str | None, env_key: str) -> ApiKeyStatus:
    if ui_key:
        return ApiKeyStatus(is_set=True, hint=ui_key[-4:], source="ui")
    if env_key:
        return ApiKeyStatus(is_set=True, hint=env_key[-4:], source="environment")
    return ApiKeyStatus(is_set=False)


def _view(settings: Settings, row: LLMSettingsRow | None) -> LLMSettingsView:
    env_anthropic = _secret(settings.anthropic_api_key)
    env_openai = _secret(settings.openai_api_key)
    if row is None:
        return LLMSettingsView(
            provider=settings.llm_provider,
            base_url=settings.llm_base_url,
            models=_models_from(settings),
            anthropic_key=_status(None, env_anthropic),
            openai_key=_status(None, env_openai),
            source="environment",
            updated_at=None,
        )
    provider: str = row.provider
    assert provider in ("anthropic", "openai", "fake")
    return LLMSettingsView(
        provider=provider,
        base_url=row.base_url,
        models=AgentModels(**row.models),
        anthropic_key=_status(_stored_key(settings, row.anthropic_api_key_enc), env_anthropic),
        openai_key=_status(_stored_key(settings, row.openai_api_key_enc), env_openai),
        source="ui",
        updated_at=row.updated_at,
    )


def _overlay(
    settings: Settings,
    row: LLMSettingsRow,
) -> Settings:
    update: dict[str, object] = {
        "llm_provider": row.provider,
        "llm_base_url": row.base_url,
        **row.models,
    }
    for field, enc in (
        ("anthropic_api_key", row.anthropic_api_key_enc),
        ("openai_api_key", row.openai_api_key_enc),
    ):
        key = _stored_key(settings, enc)
        if key:
            update[field] = SecretStr(key)
    return settings.model_copy(update=update)


async def effective_settings(
    sessionmaker: async_sessionmaker[AsyncSession], settings: Settings, user_id: uuid.UUID
) -> Settings:
    async with sessionmaker() as session:
        row = await repo.get(session, user_id)
    return settings if row is None else _overlay(settings, row)


async def get_view(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID
) -> LLMSettingsView:
    return _view(settings, await repo.get(session, user_id))


async def put(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, body: LLMSettingsUpdate
) -> LLMSettingsView:
    base_url = _normalise_base_url(body.base_url)
    row = await repo.get(session, user_id)
    anthropic_enc = row.anthropic_api_key_enc if row else None
    openai_enc = row.openai_api_key_enc if row else None
    new_key = _secret(body.api_key).strip()
    try:
        if body.provider == "anthropic":
            if body.clear_api_key:
                anthropic_enc = None
            if new_key:
                anthropic_enc = encrypt(settings, new_key)
        elif body.provider == "openai":
            if body.clear_api_key:
                openai_enc = None
            if new_key:
                openai_enc = encrypt(settings, new_key)
    except SecretsError as exc:
        raise InvalidLLMSettingsError(str(exc), code="encryption_unavailable") from exc
    saved = await repo.upsert(
        session,
        user_id,
        provider=body.provider,
        base_url=base_url,
        anthropic_api_key_enc=anthropic_enc,
        openai_api_key_enc=openai_enc,
        models=body.models.model_dump(),
    )
    return _view(settings, saved)


async def reset(session: AsyncSession, settings: Settings, user_id: uuid.UUID) -> LLMSettingsView:
    """Drops the saved configuration, so the environment decides again."""
    await repo.delete(session, user_id)
    return _view(settings, None)


class _Ping(BaseModel):
    ok: bool


async def test_connection(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, body: LLMSettingsUpdate
) -> LLMConnectionTest:
    """One tiny real call with the submitted (or else saved) key and the Scout's model."""
    model = body.models.scout_model
    if body.provider == "fake":
        return LLMConnectionTest(ok=True, model=model, message="Offline mode needs no connection.")
    base_url = _normalise_base_url(body.base_url)
    row = await repo.get(session, user_id)
    update: dict[str, object] = {
        "llm_provider": body.provider,
        "llm_base_url": base_url,
        "llm_max_validation_retries": 0,
        **body.models.model_dump(),
    }
    typed = _secret(body.api_key).strip()
    if typed:
        update["anthropic_api_key" if body.provider == "anthropic" else "openai_api_key"] = (
            SecretStr(typed)
        )
    elif row is not None:
        stored = _stored_key(
            settings,
            row.anthropic_api_key_enc if body.provider == "anthropic" else row.openai_api_key_enc,
        )
        if stored:
            update["anthropic_api_key" if body.provider == "anthropic" else "openai_api_key"] = (
                SecretStr(stored)
            )
    candidate = settings.model_copy(update=update)
    secrets = [typed] + [
        _secret(getattr(candidate, name)) for name in ("anthropic_api_key", "openai_api_key")
    ]

    def redact(text: str) -> str:
        for secret in filter(None, secrets):
            text = text.replace(secret, "***")
        return text

    request = LLMRequest(
        agent="settings_test",
        model=model,
        system='Connectivity check. Reply with the JSON object {"ok": true}.',
        messages=[ChatMessage(role="user", content="ping")],
        output_type=_Ping,
        max_tokens=64,
    )
    started = time.monotonic()
    try:
        llm = build_llm(candidate)
        await asyncio.wait_for(llm.generate(request), TEST_TIMEOUT_S)
    except TimeoutError:
        return LLMConnectionTest(
            ok=False, model=model, message=f"No answer within {int(TEST_TIMEOUT_S)} seconds."
        )
    except Exception as exc:
        return LLMConnectionTest(
            ok=False, model=model, message=redact(f"{type(exc).__name__}: {exc}")[:500]
        )
    return LLMConnectionTest(
        ok=True,
        model=model,
        message="Connected.",
        latency_ms=int((time.monotonic() - started) * 1000),
    )


def catalog() -> LLMCatalog:
    models = [
        CatalogModel(
            id=name,
            provider="anthropic" if name.startswith("claude-") else "openai",
            input_per_mtok=price.input_per_mtok,
            output_per_mtok=price.output_per_mtok,
        )
        for name, price in PRICES.items()
    ]
    return LLMCatalog(
        models=models,
        presets={name: AgentModels(**preset) for name, preset in MODEL_PRESETS.items()},
    )
