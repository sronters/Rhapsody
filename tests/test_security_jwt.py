from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.security import create_jwt, verify_jwt


def test_create_and_verify_jwt_round_trip() -> None:
    settings = Settings(jwt_signing_key="test-signing-key")
    token = create_jwt("00000000-0000-0000-0000-000000000001", settings)

    payload = verify_jwt(token, settings)

    assert payload["sub"] == "00000000-0000-0000-0000-000000000001"


def test_verify_jwt_rejects_tampering() -> None:
    settings = Settings(jwt_signing_key="test-signing-key")
    token = create_jwt("user", settings)
    tampered = token.rsplit(".", maxsplit=1)[0] + ".bad"

    with pytest.raises(ValueError):
        verify_jwt(tampered, settings)


def test_verify_jwt_rejects_expired_token() -> None:
    settings = Settings(jwt_signing_key="test-signing-key")
    token = create_jwt("user", settings, expires_in_seconds=-1)

    with pytest.raises(ValueError):
        verify_jwt(token, settings)