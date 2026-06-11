from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Decision, MemoryChunk
from app.repositories.workspace import WorkspaceRepository
from app.schemas.decisions import DecisionCreate
from app.services.embeddings import EmbeddingService


class DecisionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workspace_repository = WorkspaceRepository(session)
        self.embedding_service = EmbeddingService()

    async def create(self, payload: DecisionCreate) -> Decision:
        workspace = await self.workspace_repository.get(payload.workspace_id)
        decision = Decision(**payload.model_dump())
        self.session.add(decision)
        await self.session.flush()
        self.session.add(
            MemoryChunk(
                workspace_id=payload.workspace_id,
                source_type="decision",
                source_id=decision.id,
                source_title=payload.title,
                content=f"{payload.title}\n\nRationale: {payload.rationale}",
                embedding=self.embedding_service.embed_for_storage(
                    f"{payload.title}\n\nRationale: {payload.rationale}"
                ),
            )
        )
        self.session.add(
            AuditLog(
                organization_id=workspace.organization_id,
                workspace_id=payload.workspace_id,
                action="decision.created",
                resource_type="decision",
                resource_id=decision.id,
                metadata_json={"source_type": payload.source_type},
            )
        )
        await self.session.commit()
        return decision

    async def list_for_workspace(self, workspace_id: UUID) -> list[Decision]:
        return list(
            (
                await self.session.scalars(
                    select(Decision)
                    .where(Decision.workspace_id == workspace_id)
                    .order_by(Decision.created_at.desc())
                )
            ).all()
        )
