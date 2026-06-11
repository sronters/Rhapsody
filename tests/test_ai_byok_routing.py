from __future__ import annotations

import uuid

import pytest

from app.core.config import Settings
from app.db.models import EncryptedAPIKey, Workspace
from app.services.ai import AIRouter, LLMRequest, OpenAICompatibleProvider
from app.services.crypto import SecretCipher


class _ScalarResult:
    def __init__(self, rows: list[object]) -> None:
        self.rows = rows

    def first(self) -> object | None:
        return self.rows[0] if self.rows else None

    def one_or_none(self) -> object | None:
        return self.rows[0] if self.rows else None


class _FakeSession:
    def __init__(self, workspace: Workspace | None, provider_key: EncryptedAPIKey | None) -> None:
        self.workspace = workspace
        self.provider_key = provider_key

    async def scalars(self, statement: object) -> _ScalarResult:
        statement_text = str(statement)
        if "FROM workspaces" in statement_text:
            return _ScalarResult([self.workspace] if self.workspace else [])
        if "FROM encrypted_api_keys" in statement_text:
            return _ScalarResult([self.provider_key] if self.provider_key else [])
        raise AssertionError(f"Unexpected query: {statement_text}")


@pytest.mark.asyncio
async def test_byok_router_uses_encrypted_openrouter_key_for_workspace_org() -> None:
    organization_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    cipher = SecretCipher(SecretCipher.generate_key())
    workspace = Workspace(id=workspace_id, organization_id=organization_id, name="Ops")
    provider_key = EncryptedAPIKey(
        organization_id=organization_id,
        provider="openrouter",
        ciphertext=cipher.encrypt("customer-openrouter-key"),
    )
    router = AIRouter(
        settings=Settings(deployment_mode="byok", encryption_key=SecretCipher.generate_key()),
        session=_FakeSession(workspace, provider_key),  # type: ignore[arg-type]
        cipher=cipher,
    )

    provider = await router.byok_provider_for_request(
        LLMRequest(workspace_id=str(workspace_id), purpose="memory_qa", prompt="Question"),
        provider_hint="openrouter",
    )

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.name == "openrouter"
    assert provider.api_key == "customer-openrouter-key"


@pytest.mark.asyncio
async def test_byok_router_falls_back_when_no_customer_key_exists() -> None:
    workspace_id = uuid.uuid4()
    workspace = Workspace(id=workspace_id, organization_id=uuid.uuid4(), name="Ops")
    router = AIRouter(
        settings=Settings(deployment_mode="byok", encryption_key=SecretCipher.generate_key()),
        session=_FakeSession(workspace, None),  # type: ignore[arg-type]
        cipher=SecretCipher(SecretCipher.generate_key()),
    )

    provider = await router.byok_provider_for_request(
        LLMRequest(workspace_id=str(workspace_id), purpose="memory_qa", prompt="Question"),
        provider_hint="openrouter",
    )

    assert provider is None