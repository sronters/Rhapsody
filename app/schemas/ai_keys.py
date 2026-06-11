from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ProviderKeyUpsert(BaseModel):
    workspace_id: UUID
    organization_id: UUID
    provider: str = Field(pattern="^(openai|openrouter|anthropic|gemini|azure_openai)$")
    api_key: str = Field(min_length=8, max_length=4096)


class ProviderKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    provider: str
    created_at: datetime


class ProviderKeyDelete(BaseModel):
    workspace_id: UUID
    organization_id: UUID
    provider: str = Field(pattern="^(openai|openrouter|anthropic|gemini|azure_openai)$")
