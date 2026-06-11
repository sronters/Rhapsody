from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DeploymentMode = Literal["cloud", "byok", "private"]
Environment = Literal["development", "test", "staging", "production"]
AIMode = Literal["openai", "openrouter", "gemini", "ollama"]
STTMode = Literal["openai", "local_whisper"]
VisionMode = Literal["openai", "gemini"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Rhapsody"
    environment: Environment = "development"
    deployment_mode: DeploymentMode = "cloud"
    ai_mode: AIMode | None = None
    api_base_url: str = "http://localhost:8000"
    database_url: str = "postgresql+asyncpg://rhapsody:rhapsody@localhost:5432/rhapsody"
    redis_url: str = "redis://localhost:6379/0"
    service_api_keys: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["local-dev-key"]
    )
    encryption_key: str = "replace-with-fernet-key"
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-02-15-preview"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    local_llm_base_url: str = "http://localhost:11434"
    stt_mode: STTMode | None = None
    local_whisper_model: str = "small"
    local_whisper_device: str = "cpu"
    local_whisper_compute_type: str = "int8"
    local_whisper_language: str | None = "ru"
    vision_mode: VisionMode | None = None
    listener_enabled: bool = False
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    telegram_user_session: str | None = None
    listener_storage_dir: str = "/tmp/rhapsody-listener"  # noqa: S108 - operator-configurable.
    live_transcription_chunk_seconds: int = 30
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_bucket: str = "rhapsody"
    sentry_dsn: str | None = None
    jwt_signing_key: str = "replace-with-jwt-signing-key"
    jwt_issuer: str = "rhapsody"
    jwt_audience: str = "rhapsody-api"
    rate_limit_per_minute: int = 120
    log_level: str = "INFO"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000"]
    )

    @field_validator("service_api_keys", "cors_origins", mode="before")
    @classmethod
    def split_csv(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                parsed = json.loads(stripped)
                if not isinstance(parsed, list) or not all(
                    isinstance(item, str) for item in parsed
                ):
                    raise ValueError("Expected a JSON list of strings.")
                return [item.strip() for item in parsed if item.strip()]
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator(
        "ai_mode",
        "stt_mode",
        "vision_mode",
        "local_whisper_language",
        "telegram_api_id",
        mode="before",
    )
    @classmethod
    def blank_optional_values_are_unset(cls, value: object) -> object:
        if value == "":
            return None
        return value

    @property
    def is_non_prod(self) -> bool:
        return self.environment in {"development", "test", "staging"}

    @property
    def has_default_encryption_key(self) -> bool:
        return self.encryption_key == "replace-with-fernet-key"


@lru_cache
def get_settings() -> Settings:
    return Settings()
