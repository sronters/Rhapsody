from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    workspace_id: UUID | None
    actor_user_id: UUID | None
    action: str
    resource_type: str
    resource_id: UUID | None
    metadata_json: dict
    created_at: datetime
