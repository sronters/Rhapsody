from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services import provider_keys
from app.services.crypto import SecretCipher
from app.services.provider_keys import ProviderKeyService


def test_provider_key_cipher_round_trip() -> None:
    cipher = SecretCipher(SecretCipher.generate_key())
    plaintext = "provider-token-value"
    encrypted = cipher.encrypt(plaintext)

    assert encrypted != plaintext
    assert cipher.decrypt(encrypted) == plaintext


def test_provider_key_service_rejects_default_encryption_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_keys, "get_settings", lambda: Settings(_env_file=None))

    with pytest.raises(ValueError, match="ENCRYPTION_KEY must be configured"):
        ProviderKeyService(session=None)  # type: ignore[arg-type]
