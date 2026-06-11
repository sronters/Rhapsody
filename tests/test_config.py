from __future__ import annotations

from app.core.config import Settings


def test_service_api_keys_accept_comma_separated_string() -> None:
    settings = Settings(service_api_keys="local-dev-key,second-key")

    assert settings.service_api_keys == ["local-dev-key", "second-key"]


def test_service_api_keys_accept_json_list_string() -> None:
    settings = Settings(service_api_keys='["local-dev-key", "second-key"]')

    assert settings.service_api_keys == ["local-dev-key", "second-key"]


def test_cors_origins_accept_comma_separated_string() -> None:
    settings = Settings(cors_origins="http://localhost:3000,http://localhost:3001")

    assert settings.cors_origins == ["http://localhost:3000", "http://localhost:3001"]


def test_detects_default_encryption_key() -> None:
    assert Settings(encryption_key="replace-with-fernet-key").has_default_encryption_key
    assert not Settings(encryption_key="real-fernet-key").has_default_encryption_key