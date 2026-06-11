from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TaskCreate(BaseModel):
    workspace_id: UUID
    title: str = Field(min_length=2, max_length=320)
    description: str | None = Field(default=None, max_length=8000)
    assignee_user_id: UUID | None = None
    due_at: datetime | None = None
    source_type: str = Field(default="manual", max_length=40)
    source_id: UUID | None = None


class TaskStatusUpdate(BaseModel):
    workspace_id: UUID
    status: str = Field(pattern="^(open|in_progress|blocked|done|cancelled)$")


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    title: str
    description: str | None
    assignee_user_id: UUID | None
    status: str
    due_at: datetime | None
    source_type: str
    source_id: UUID | None
