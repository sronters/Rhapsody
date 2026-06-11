from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.api.deps import DBSession, ServiceAuth
from app.core.rbac import Permission
from app.schemas.tasks import TaskCreate, TaskRead, TaskStatusUpdate
from app.services.access import AccessService
from app.services.tasks import TaskService

router = APIRouter()


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
async def create_task(
    payload: TaskCreate,
    session: DBSession,
    _: ServiceAuth,
    actor_user_id: Annotated[UUID, Query()],
) -> TaskRead:
    await AccessService(session).require_workspace_permission(
        payload.workspace_id, actor_user_id, Permission.MANAGE_TASKS
    )
    return await TaskService(session).create(payload)


@router.get("", response_model=list[TaskRead])
async def list_tasks(
    session: DBSession,
    _: ServiceAuth,
    workspace_id: Annotated[UUID, Query()],
    actor_user_id: Annotated[UUID, Query()],
) -> list[TaskRead]:
    await AccessService(session).require_workspace_permission(
        workspace_id, actor_user_id, Permission.READ_MEMORY
    )
    return await TaskService(session).list_for_workspace(workspace_id)


@router.patch("/{task_id}/status", response_model=TaskRead)
async def update_task_status(
    task_id: UUID,
    payload: TaskStatusUpdate,
    session: DBSession,
    _: ServiceAuth,
    actor_user_id: Annotated[UUID, Query()],
) -> TaskRead:
    await AccessService(session).require_workspace_permission(
        payload.workspace_id, actor_user_id, Permission.MANAGE_TASKS
    )
    return await TaskService(session).update_status(task_id, payload)
