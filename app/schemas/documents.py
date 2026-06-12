from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DocumentIngestRequest(BaseModel):
    workspace_id: UUID
    name: str = Field(min_length=2, max_length=240)
    content_type: str = Field(min_length=3, max_length=120)
    storage_key: str = Field(min_length=2, max_length=512)
    extracted_text: str = Field(min_length=1, max_length=500_000)
    uploaded_by_user_id: UUID | None = None
    telegram_chat_id: int | None = None
    telegram_message_id: int | None = None


class DocumentIngestResponse(BaseModel):
    document_id: UUID
    chunks_created: int


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    uploaded_by_user_id: UUID | None
    telegram_chat_id: int | None
    telegram_message_id: int | None
    name: str
    content_type: str
    storage_key: str
