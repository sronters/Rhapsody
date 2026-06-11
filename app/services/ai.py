from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import Settings, get_settings
from app.db.models import EncryptedAPIKey, Workspace
from app.services.crypto import SecretCipher


@dataclass(frozen=True)
class LLMRequest:
    workspace_id: str
    purpose: str
    prompt: str
    model: str | None = None
    temperature: float = 0.0


@dataclass(frozen=True)
class LLMResponse:
    provider: str
    model: str
    text: str
    prompt_hash: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    estimated_cost_usd: float = 0.0


class LLMProvider(ABC):
    name: str
    default_model: str

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError


class DeterministicLocalProvider(LLMProvider):
    name = "deterministic-local"
    default_model = "teammind-rules-v1"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        text = (
            "I found relevant TeamMind memory. Use the cited sources below as the "
            "ground truth before making operational decisions."
        )
        return LLMResponse(
            provider=self.name,
            model=request.model or self.default_model,
            text=text,
            prompt_hash=_hash_prompt(request.prompt),
            input_tokens=_rough_token_count(request.prompt),
            output_tokens=_rough_token_count(text),
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, name: str, api_key: str, base_url: str, default_model: str) -> None:
        self.name = name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": request.model or self.default_model,
                    "temperature": request.temperature,
                    "messages": [{"role": "user", "content": request.prompt}],
                },
            )
            response.raise_for_status()
            payload = response.json()
        text = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
        return LLMResponse(
            provider=self.name,
            model=request.model or self.default_model,
            text=text,
            prompt_hash=_hash_prompt(request.prompt),
            input_tokens=usage.get("prompt_tokens", _rough_token_count(request.prompt)),
            output_tokens=usage.get("completion_tokens", _rough_token_count(text)),
            latency_ms=int((time.perf_counter() - started) * 1000),
            estimated_cost_usd=estimate_llm_cost_usd(
                self.name,
                request.model or self.default_model,
                usage.get("prompt_tokens", _rough_token_count(request.prompt)),
                usage.get("completion_tokens", _rough_token_count(text)),
            ),
        )


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_model = "claude-3-5-haiku-latest"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        model = request.model or self.default_model
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": model,
                    "max_tokens": 2048,
                    "temperature": request.temperature,
                    "messages": [{"role": "user", "content": request.prompt}],
                },
            )
            response.raise_for_status()
            payload = response.json()
        text = "".join(block.get("text", "") for block in payload.get("content", []))
        usage = payload.get("usage", {})
        input_tokens = usage.get("input_tokens", _rough_token_count(request.prompt))
        output_tokens = usage.get("output_tokens", _rough_token_count(text))
        return LLMResponse(
            provider=self.name,
            model=model,
            text=text,
            prompt_hash=_hash_prompt(request.prompt),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            estimated_cost_usd=estimate_llm_cost_usd(
                self.name, model, input_tokens, output_tokens
            ),
        )


class GeminiProvider(LLMProvider):
    name = "gemini"
    default_model = "gemini-2.5-flash"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        model = request.model or self.default_model
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": self.api_key},
                json={
                    "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
                    "generationConfig": {"temperature": request.temperature},
                },
            )
            response.raise_for_status()
            payload = response.json()
        text = extract_gemini_text(payload)
        usage = payload.get("usageMetadata", {})
        input_tokens = usage.get("promptTokenCount", _rough_token_count(request.prompt))
        output_tokens = usage.get("candidatesTokenCount", _rough_token_count(text))
        return LLMResponse(
            provider=self.name,
            model=model,
            text=text,
            prompt_hash=_hash_prompt(request.prompt),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            estimated_cost_usd=estimate_llm_cost_usd(
                self.name, model, input_tokens, output_tokens
            ),
        )


class AzureOpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, endpoint: str, deployment: str, api_version: str) -> None:
        super().__init__(
            name="azure-openai",
            api_key=api_key,
            base_url=endpoint.rstrip("/"),
            default_model=deployment,
        )
        self.api_version = api_version

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    async def generate(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        model = request.model or self.default_model
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.post(
                f"{self.base_url}/openai/deployments/{model}/chat/completions",
                params={"api-version": self.api_version},
                headers={"api-key": self.api_key},
                json={
                    "temperature": request.temperature,
                    "messages": [{"role": "user", "content": request.prompt}],
                },
            )
            response.raise_for_status()
            payload = response.json()
        text = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
        input_tokens = usage.get("prompt_tokens", _rough_token_count(request.prompt))
        output_tokens = usage.get("completion_tokens", _rough_token_count(text))
        return LLMResponse(
            provider=self.name,
            model=model,
            text=text,
            prompt_hash=_hash_prompt(request.prompt),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            estimated_cost_usd=estimate_llm_cost_usd(
                self.name, model, input_tokens, output_tokens
            ),
        )


class AIRouter:
    def __init__(
        self,
        settings: Settings | None = None,
        session: AsyncSession | None = None,
        cipher: SecretCipher | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session = session
        self.cipher = cipher or SecretCipher(self.settings.encryption_key)

    def provider_for_request(self, provider_hint: str | None = None) -> LLMProvider:
        if self.settings.deployment_mode == "private":
            return OpenAICompatibleProvider(
                name="local",
                api_key="local",
                base_url=f"{self.settings.local_llm_base_url}/v1",
                default_model="qwen2.5",
            )
        if provider_hint == "openrouter" and self.settings.openrouter_api_key:
            return OpenAICompatibleProvider(
                name="openrouter",
                api_key=self.settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                default_model="openai/gpt-4o-mini",
            )
        if provider_hint == "anthropic" and self.settings.anthropic_api_key:
            return AnthropicProvider(api_key=self.settings.anthropic_api_key)
        if provider_hint == "gemini" and self.settings.gemini_api_key:
            return GeminiProvider(api_key=self.settings.gemini_api_key)
        if provider_hint == "azure-openai" and self.settings.azure_openai_api_key:
            if not self.settings.azure_openai_endpoint or not self.settings.azure_openai_deployment:
                if self.settings.is_non_prod:
                    return DeterministicLocalProvider()
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Azure OpenAI is not fully configured.",
                )
            return AzureOpenAIProvider(
                api_key=self.settings.azure_openai_api_key,
                endpoint=self.settings.azure_openai_endpoint,
                deployment=self.settings.azure_openai_deployment,
                api_version=self.settings.azure_openai_api_version,
            )
        if self.settings.openai_api_key:
            return OpenAICompatibleProvider(
                name="openai",
                api_key=self.settings.openai_api_key,
                base_url="https://api.openai.com/v1",
                default_model="gpt-4o-mini",
            )
        if self.settings.is_non_prod:
            return DeterministicLocalProvider()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No AI provider is configured for this environment.",
        )

    async def generate(self, request: LLMRequest, provider_hint: str | None = None) -> LLMResponse:
        byok_provider = await self.byok_provider_for_request(request, provider_hint)
        if byok_provider:
            return await byok_provider.generate(request)
        provider = self.provider_for_request(provider_hint)
        return await provider.generate(request)

    async def byok_provider_for_request(
        self, request: LLMRequest, provider_hint: str | None = None
    ) -> LLMProvider | None:
        if self.settings.deployment_mode != "byok" or self.session is None:
            return None
        provider_name = provider_hint or "openai"
        provider_key = await self._load_byok_provider_key(
            workspace_id=UUID(request.workspace_id),
            provider=provider_name,
        )
        if provider_key is None:
            return None
        return build_openai_compatible_provider(
            provider=provider_key.provider,
            api_key=self.cipher.decrypt(provider_key.ciphertext),
            settings=self.settings,
        )

    async def _load_byok_provider_key(
        self, workspace_id: UUID, provider: str
    ) -> EncryptedAPIKey | None:
        if provider not in BYOK_OPENAI_COMPATIBLE_PROVIDERS:
            return None
        workspace = (
            await self.session.scalars(select(Workspace).where(Workspace.id == workspace_id))
        ).one_or_none()
        if workspace is None:
            return None
        return (
            await self.session.scalars(
                select(EncryptedAPIKey).where(
                    EncryptedAPIKey.organization_id == workspace.organization_id,
                    EncryptedAPIKey.provider == provider,
                )
            )
        ).first()


BYOK_OPENAI_COMPATIBLE_PROVIDERS = frozenset({"openai", "openrouter"})


MODEL_PRICING_PER_MILLION_TOKENS: dict[tuple[str, str], tuple[float, float]] = {
    ("openai", "gpt-4o-mini"): (0.15, 0.60),
    ("openrouter", "openai/gpt-4o-mini"): (0.15, 0.60),
    ("anthropic", "claude-3-5-haiku-latest"): (0.80, 4.00),
    ("gemini", "gemini-2.5-flash"): (0.30, 2.50),
}


def build_openai_compatible_provider(
    provider: str, api_key: str, settings: Settings
) -> OpenAICompatibleProvider:
    if provider == "openrouter":
        return OpenAICompatibleProvider(
            name="openrouter",
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
            default_model="openai/gpt-4o-mini",
        )
    if provider == "openai":
        return OpenAICompatibleProvider(
            name="openai",
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            default_model="gpt-4o-mini",
        )
    raise ValueError(f"Unsupported OpenAI-compatible provider: {provider}")


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()


def _rough_token_count(text: str) -> int:
    return max(1, len(text.split()))


def extract_gemini_text(payload: dict) -> str:
    candidates = payload.get("candidates", [])
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def estimate_llm_cost_usd(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    input_price, output_price = MODEL_PRICING_PER_MILLION_TOKENS.get(
        (provider, model),
        (0.0, 0.0),
    )
    return round(
        (input_tokens / 1_000_000 * input_price)
        + (output_tokens / 1_000_000 * output_price),
        8,
    )
