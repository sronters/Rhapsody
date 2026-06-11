from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Workspace, WorkspaceMember


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, workspace_id: UUID) -> Workspace:
        return (
            await self.session.scalars(select(Workspace).where(Workspace.id == workspace_id))
        ).one()

    async def get_member(self, workspace_id: UUID, user_id: UUID) -> WorkspaceMember | None:
        return (
            await self.session.scalars(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                )
            )
        ).first()
