from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    deployment_mode: str = Field(default="cloud", pattern="^(cloud|byok|private)$")
    retention_mode: str = Field(default="standard", pattern="^(standard|no_retention|ephemeral)$")


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    deployment_mode: str
    retention_mode: str


class WorkspaceCreate(BaseModel):
    organization_id: UUID
    name: str = Field(min_length=2, max_length=160)


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str


class UserCreate(BaseModel):
    telegram_user_id: int | None = None
    display_name: str = Field(min_length=1, max_length=160)
    email: str | None = Field(default=None, max_length=320)


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    telegram_user_id: int | None
    display_name: str
    email: str | None


class WorkspaceMemberCreate(BaseModel):
    user_id: UUID
    role: str = Field(pattern="^(member|team_lead|manager|admin|enterprise_admin)$")


class WorkspaceMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    user_id: UUID
    role: str
