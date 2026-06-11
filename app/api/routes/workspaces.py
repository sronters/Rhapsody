from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, status
from sqlalchemy import select

from app.api.deps import DBSession, ServiceAuth
from app.db.models import AuditLog, Organization, User, Workspace, WorkspaceMember
from app.schemas.workspaces import (
    OrganizationCreate,
    OrganizationRead,
    UserCreate,
    UserRead,
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberRead,
    WorkspaceRead,
)

router = APIRouter()


@router.post("/organizations", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate, session: DBSession, _: ServiceAuth
) -> Organization:
    organization = Organization(
        name=payload.name,
        deployment_mode=payload.deployment_mode,
        retention_mode=payload.retention_mode,
    )
    session.add(organization)
    await session.flush()
    session.add(
        AuditLog(
            organization_id=organization.id,
            action="organization.created",
            resource_type="organization",
            resource_id=organization.id,
            metadata_json={"deployment_mode": payload.deployment_mode},
        )
    )
    await session.commit()
    return organization


@router.post("", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate, session: DBSession, _: ServiceAuth
) -> Workspace:
    workspace = Workspace(organization_id=payload.organization_id, name=payload.name)
    session.add(workspace)
    await session.flush()
    session.add(
        AuditLog(
            organization_id=payload.organization_id,
            workspace_id=workspace.id,
            action="workspace.created",
            resource_type="workspace",
            resource_id=workspace.id,
            metadata_json={},
        )
    )
    await session.commit()
    return workspace


@router.get("/{workspace_id}", response_model=WorkspaceRead)
async def get_workspace(workspace_id: UUID, session: DBSession, _: ServiceAuth) -> Workspace:
    return (await session.scalars(select(Workspace).where(Workspace.id == workspace_id))).one()


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, session: DBSession, _: ServiceAuth) -> User:
    user = User(**payload.model_dump())
    session.add(user)
    await session.commit()
    return user


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_workspace_member(
    workspace_id: UUID,
    payload: WorkspaceMemberCreate,
    session: DBSession,
    _: ServiceAuth,
) -> WorkspaceMember:
    workspace = (await session.scalars(select(Workspace).where(Workspace.id == workspace_id))).one()
    member = WorkspaceMember(workspace_id=workspace_id, user_id=payload.user_id, role=payload.role)
    session.add(member)
    await session.flush()
    session.add(
        AuditLog(
            organization_id=workspace.organization_id,
            workspace_id=workspace_id,
            actor_user_id=payload.user_id,
            action="workspace.member_added",
            resource_type="workspace_member",
            resource_id=member.id,
            metadata_json={"role": payload.role},
        )
    )
    await session.commit()
    return member


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberRead])
async def list_workspace_members(
    workspace_id: UUID, session: DBSession, _: ServiceAuth
) -> list[WorkspaceMember]:
    return list(
        (
            await session.scalars(
                select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
            )
        ).all()
    )
