from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import DBSession, ServiceAuth
from app.core.rbac import Permission
from app.schemas.decisions import DecisionCreate, DecisionRead
from app.services.access import AccessService
from app.services.decisions import DecisionService

router = APIRouter()


@router.post("", response_model=DecisionRead, status_code=status.HTTP_201_CREATED)
async def create_decision(
    payload: DecisionCreate,
    session: DBSession,
    _: ServiceAuth,
    actor_user_id: Annotated[UUID, Query()],
) -> DecisionRead:
    await AccessService(session).require_workspace_permission(
        payload.workspace_id, actor_user_id, Permission.MANAGE_DECISIONS
    )
    return await DecisionService(session).create(payload)


@router.get("", response_model=list[DecisionRead])
async def list_decisions(
    session: DBSession,
    _: ServiceAuth,
    workspace_id: Annotated[UUID, Query()],
    actor_user_id: Annotated[UUID, Query()],
) -> list[DecisionRead]:
    await AccessService(session).require_workspace_permission(
        workspace_id, actor_user_id, Permission.READ_MEMORY
    )
    return await DecisionService(session).list_for_workspace(workspace_id)
