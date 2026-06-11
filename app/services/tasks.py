from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, Task
from app.repositories.workspace import WorkspaceRepository
from app.schemas.tasks import TaskCreate, TaskStatusUpdate


class TaskService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.workspace_repository = WorkspaceRepository(session)

    async def create(self, payload: TaskCreate) -> Task:
        workspace = await self.workspace_repository.get(payload.workspace_id)
        task = Task(**payload.model_dump(), status="open")
        self.session.add(task)
        await self.session.flush()
        self.session.add(
            AuditLog(
                organization_id=workspace.organization_id,
                workspace_id=payload.workspace_id,
                action="task.created",
                resource_type="task",
                resource_id=task.id,
                metadata_json={"source_type": payload.source_type},
            )
        )
        await self.session.commit()
        return task

    async def list_for_workspace(self, workspace_id: UUID) -> list[Task]:
        return list(
            (
                await self.session.scalars(
                    select(Task)
                    .where(Task.workspace_id == workspace_id)
                    .order_by(Task.created_at.desc())
                )
            ).all()
        )

    async def update_status(self, task_id: UUID, payload: TaskStatusUpdate) -> Task:
        workspace = await self.workspace_repository.get(payload.workspace_id)
        task = (
            await self.session.scalars(
                select(Task).where(Task.id == task_id, Task.workspace_id == payload.workspace_id)
            )
        ).one()
        previous_status = task.status
        task.status = payload.status
        self.session.add(
            AuditLog(
                organization_id=workspace.organization_id,
                workspace_id=payload.workspace_id,
                action="task.status_updated",
                resource_type="task",
                resource_id=task.id,
                metadata_json={"from": previous_status, "to": payload.status},
            )
        )
        await self.session.commit()
        return task
