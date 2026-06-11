from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_workspace(self, workspace_id: UUID, limit: int = 100) -> list[AuditLog]:
        return list(
            (
                await self.session.scalars(
                    select(AuditLog)
                    .where(AuditLog.workspace_id == workspace_id)
                    .order_by(AuditLog.created_at.desc())
                    .limit(limit)
                )
            ).all()
        )
