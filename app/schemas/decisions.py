from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DecisionCreate(BaseModel):
    workspace_id: UUID
    title: str = Field(min_length=2, max_length=320)
    rationale: str = Field(min_length=2, max_length=12000)
    source_type: str = Field(default="manual", max_length=40)
    source_id: UUID | None = None


class DecisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    title: str
    rationale: str
    source_type: str
    source_id: UUID | None
