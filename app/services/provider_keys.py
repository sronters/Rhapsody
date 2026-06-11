from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import AuditLog, EncryptedAPIKey
from app.schemas.ai_keys import ProviderKeyDelete, ProviderKeyUpsert
from app.services.crypto import SecretCipher


class ProviderKeyService:
    def __init__(self, session: AsyncSession, cipher: SecretCipher | None = None) -> None:
        self.session = session
        settings = get_settings()
        if cipher is None and settings.has_default_encryption_key:
            raise ValueError("ENCRYPTION_KEY must be configured before storing provider keys.")
        self.cipher = cipher or SecretCipher(settings.encryption_key)

    async def upsert(self, payload: ProviderKeyUpsert) -> EncryptedAPIKey:
        existing = (
            await self.session.scalars(
                select(EncryptedAPIKey).where(
                    EncryptedAPIKey.organization_id == payload.organization_id,
                    EncryptedAPIKey.provider == payload.provider,
                )
            )
        ).first()
        ciphertext = self.cipher.encrypt(payload.api_key)
        if existing:
            existing.ciphertext = ciphertext
            provider_key = existing
            action = "provider_key.updated"
        else:
            provider_key = EncryptedAPIKey(
                organization_id=payload.organization_id,
                provider=payload.provider,
                ciphertext=ciphertext,
            )
            self.session.add(provider_key)
            action = "provider_key.created"

        await self.session.flush()
        self.session.add(
            AuditLog(
                organization_id=payload.organization_id,
                workspace_id=payload.workspace_id,
                action=action,
                resource_type="provider_key",
                resource_id=provider_key.id,
                metadata_json={"provider": payload.provider},
            )
        )
        await self.session.commit()
        return provider_key

    async def list_for_organization(self, organization_id: UUID) -> list[EncryptedAPIKey]:
        return list(
            (
                await self.session.scalars(
                    select(EncryptedAPIKey)
                    .where(EncryptedAPIKey.organization_id == organization_id)
                    .order_by(EncryptedAPIKey.created_at.desc())
                )
            ).all()
        )

    async def delete(self, payload: ProviderKeyDelete) -> None:
        await self.session.execute(
            delete(EncryptedAPIKey).where(
                EncryptedAPIKey.organization_id == payload.organization_id,
                EncryptedAPIKey.provider == payload.provider,
            )
        )
        self.session.add(
            AuditLog(
                organization_id=payload.organization_id,
                workspace_id=payload.workspace_id,
                action="provider_key.deleted",
                resource_type="provider_key",
                metadata_json={"provider": payload.provider},
            )
        )
        await self.session.commit()
