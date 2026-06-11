from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import DBSession, ServiceAuth
from app.core.rbac import Permission
from app.schemas.audit import AuditLogRead
from app.services.access import AccessService
from app.services.audit import AuditService

router = APIRouter()


@router.get("", response_model=list[AuditLogRead])
async def list_audit_logs(
    session: DBSession,
    _: ServiceAuth,
    workspace_id: Annotated[UUID, Query()],
    actor_user_id: Annotated[UUID, Query()],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditLogRead]:
    await AccessService(session).require_workspace_permission(
        workspace_id, actor_user_id, Permission.VIEW_AUDIT
    )
    return await AuditService(session).list_for_workspace(workspace_id, limit=limit)
