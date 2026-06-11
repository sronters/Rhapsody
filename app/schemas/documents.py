from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentIngestRequest(BaseModel):
    workspace_id: UUID
    name: str = Field(min_length=2, max_length=240)
    content_type: str = Field(min_length=3, max_length=120)
    storage_key: str = Field(min_length=2, max_length=512)
    extracted_text: str = Field(min_length=1, max_length=500_000)


class DocumentIngestResponse(BaseModel):
    document_id: UUID
    chunks_created: int


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    content_type: str
    storage_key: str
