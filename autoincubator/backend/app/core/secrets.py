"""Encryption of API keys saved from the UI (Fernet, key from SETTINGS_ENCRYPTION_KEY)."""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings


class SecretsError(RuntimeError):
    """Encryption is not configured, or a stored secret cannot be decrypted."""


def _fernet(settings: Settings) -> Fernet:
    if settings.settings_encryption_key and settings.settings_encryption_key.get_secret_value():
        try:
            return Fernet(settings.settings_encryption_key.get_secret_value().encode())
        except ValueError as exc:
            raise SecretsError(
                "SETTINGS_ENCRYPTION_KEY is not a valid Fernet key "
                "(generate one with cryptography.fernet.Fernet.generate_key())"
            ) from exc
    if settings.app_env == "production":
        raise SecretsError("SETTINGS_ENCRYPTION_KEY must be set to store API keys from the UI")
    # Development only: a fixed key keeps the API and the worker in agreement without setup.
    digest = hashlib.sha256(b"autoincubator-development-settings-key").digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(settings: Settings, plaintext: str) -> str:
    return _fernet(settings).encrypt(plaintext.encode()).decode()


def decrypt(settings: Settings, token: str) -> str:
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretsError(
            "A stored API key cannot be decrypted (SETTINGS_ENCRYPTION_KEY changed?); "
            "enter it again"
        ) from exc
