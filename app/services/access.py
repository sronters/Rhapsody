from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rbac import Permission, role_has_permission
from app.db.models import Workspace
from app.repositories.workspace import WorkspaceRepository


class AccessService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = WorkspaceRepository(session)

    async def require_workspace_permission(
        self, workspace_id: UUID, actor_user_id: UUID, permission: Permission
    ) -> None:
        member = await self.repository.get_member(workspace_id, actor_user_id)
        if member and role_has_permission(member.role, permission):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing workspace permission: {permission.value}",
        )

    async def require_workspace_in_organization(
        self, workspace_id: UUID, organization_id: UUID
    ) -> None:
        workspace = (
            await self.session.scalars(select(Workspace).where(Workspace.id == workspace_id))
        ).one_or_none()
        if workspace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Workspace not found.",
            )
        if workspace.organization_id != organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace does not belong to the requested organization.",
            )
