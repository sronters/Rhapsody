from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.config import Settings
from app.services.ai import (
    AIRouter,
    AnthropicProvider,
    AzureOpenAIProvider,
    DeterministicLocalProvider,
    GeminiProvider,
    estimate_llm_cost_usd,
    extract_gemini_text,
)
from app.services.crypto import SecretCipher


def settings_with_valid_encryption_key(**overrides: object) -> Settings:
    return Settings(_env_file=None, encryption_key=SecretCipher.generate_key(), **overrides)


def test_router_selects_anthropic_when_hint_and_key_exist() -> None:
    router = AIRouter(
        settings=settings_with_valid_encryption_key(anthropic_api_key="anthropic-key")
    )

    provider = router.provider_for_request("anthropic")

    assert isinstance(provider, AnthropicProvider)


def test_router_selects_gemini_when_hint_and_key_exist() -> None:
    router = AIRouter(settings=settings_with_valid_encryption_key(gemini_api_key="gemini-key"))

    provider = router.provider_for_request("gemini")

    assert isinstance(provider, GeminiProvider)


def test_router_selects_azure_openai_when_configuration_is_complete() -> None:
    router = AIRouter(
        settings=settings_with_valid_encryption_key(
            azure_openai_api_key="azure-key",
            azure_openai_endpoint="https://example.openai.azure.com",
            azure_openai_deployment="ops-gpt",
        )
    )

    provider = router.provider_for_request("azure-openai")

    assert isinstance(provider, AzureOpenAIProvider)
    assert provider.default_model == "ops-gpt"


def test_router_falls_back_when_azure_configuration_is_incomplete() -> None:
    router = AIRouter(settings=settings_with_valid_encryption_key(azure_openai_api_key="azure-key"))

    provider = router.provider_for_request("azure-openai")

    assert isinstance(provider, DeterministicLocalProvider)


def test_router_rejects_missing_provider_in_production() -> None:
    router = AIRouter(
        settings=settings_with_valid_encryption_key(
            environment="production",
            openai_api_key=None,
            openrouter_api_key=None,
            anthropic_api_key=None,
            gemini_api_key=None,
            azure_openai_api_key=None,
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        router.provider_for_request()

    assert exc_info.value.status_code == 503


def test_router_rejects_incomplete_azure_configuration_in_production() -> None:
    router = AIRouter(
        settings=settings_with_valid_encryption_key(
            environment="production",
            azure_openai_api_key="azure-key",
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        router.provider_for_request("azure-openai")

    assert exc_info.value.status_code == 503


def test_extract_gemini_text_concatenates_parts() -> None:
    payload = {
        "candidates": [
            {"content": {"parts": [{"text": "Hello"}, {"text": " Gemini"}]}}
        ]
    }

    assert extract_gemini_text(payload) == "Hello Gemini"


def test_estimate_llm_cost_usd_uses_model_pricing() -> None:
    assert estimate_llm_cost_usd("openai", "gpt-4o-mini", 1_000_000, 1_000_000) == 0.75


def test_estimate_llm_cost_usd_unknown_model_is_zero() -> None:
    assert estimate_llm_cost_usd("unknown", "unknown", 1_000_000, 1_000_000) == 0.0