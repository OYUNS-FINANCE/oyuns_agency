import pytest
from pydantic import SecretStr

from app.core.config import MODEL_PRESETS, Settings
from app.core.secrets import SecretsError, decrypt, encrypt
from app.db.models import LLMSettingsRow
from app.services import llm_settings as service
from app.services.schemas import AgentModels, LLMSettingsUpdate


def _settings(**kw: object) -> Settings:
    return Settings(_env_file=None, app_env="test").model_copy(update=kw)


def test_encrypt_round_trip_and_not_plaintext() -> None:
    s = _settings()
    token = encrypt(s, "sk-secret-1234")
    assert "sk-secret" not in token
    assert decrypt(s, token) == "sk-secret-1234"


def test_decrypt_with_other_key_fails() -> None:
    from cryptography.fernet import Fernet

    token = encrypt(_settings(), "sk-x")
    other = _settings(settings_encryption_key=SecretStr(Fernet.generate_key().decode()))
    with pytest.raises(SecretsError):
        decrypt(other, token)


def test_production_requires_key() -> None:
    s = Settings(_env_file=None, app_env="production")
    with pytest.raises(SecretsError):
        encrypt(s, "sk-x")


def test_view_without_row_reflects_environment_and_hides_key() -> None:
    s = _settings(llm_provider="anthropic", anthropic_api_key=SecretStr("sk-ant-abcd1234"))
    view = service._view(s, None)
    assert view.source == "environment"
    assert view.provider == "anthropic"
    assert view.anthropic_key.is_set and view.anthropic_key.hint == "1234"
    assert view.anthropic_key.source == "environment"
    assert not view.openai_key.is_set
    assert "sk-ant" not in view.model_dump_json()


def test_overlay_applies_row_over_environment() -> None:
    env = _settings(llm_provider="fake", openai_api_key=SecretStr("env-key"))
    models = MODEL_PRESETS["openai"] | {"scout_model": "my-small-model"}
    row = LLMSettingsRow(
        provider="openai",
        base_url="https://gw.example/v1",
        anthropic_api_key_enc=None,
        openai_api_key_enc=encrypt(env, "ui-key-9999"),
        models=models,
    )
    eff = service._overlay(env, row)
    assert eff.llm_provider == "openai"
    assert eff.llm_base_url == "https://gw.example/v1"
    assert eff.scout_model == "my-small-model"
    assert eff.openai_api_key is not None and eff.openai_api_key.get_secret_value() == "ui-key-9999"
    assert env.llm_provider == "fake"  # the base settings are untouched


def test_overlay_keeps_env_key_when_none_saved() -> None:
    env = _settings(openai_api_key=SecretStr("env-key"))
    row = LLMSettingsRow(
        provider="openai",
        base_url=None,
        anthropic_api_key_enc=None,
        openai_api_key_enc=None,
        models=MODEL_PRESETS["openai"],
    )
    eff = service._overlay(env, row)
    assert eff.openai_api_key is not None and eff.openai_api_key.get_secret_value() == "env-key"


@pytest.mark.parametrize("url", ["ftp://x", "not a url", "http://"])
def test_bad_base_url_rejected(url: str) -> None:
    with pytest.raises(service.InvalidLLMSettingsError):
        service._normalise_base_url(url)


def test_blank_base_url_is_none() -> None:
    assert service._normalise_base_url("  ") is None


def test_catalog_has_presets_for_both_providers_and_priced_models() -> None:
    cat = service.catalog()
    ids = {m.id for m in cat.models}
    for preset in cat.presets.values():
        assert set(preset.model_dump().values()) <= ids
    assert {m.provider for m in cat.models} == {"anthropic", "openai"}


async def test_fake_provider_test_needs_no_network() -> None:
    body = LLMSettingsUpdate(provider="fake", models=AgentModels(**MODEL_PRESETS["anthropic"]))
    result = await service.test_connection(None, _settings(), None, body)  # type: ignore[arg-type]
    assert result.ok
