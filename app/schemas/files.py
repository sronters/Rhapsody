from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class FileUploadUrlRequest(BaseModel):
    workspace_id: UUID
    filename: str = Field(min_length=1, max_length=240)
    content_type: str = Field(min_length=3, max_length=120)
    purpose: str = Field(pattern="^(meeting_recording|document|telegram_file|transcript)$")


class FileUploadUrlResponse(BaseModel):
    storage_key: str
    upload_url: str
    expires_in_seconds: int
    headers: dict[str, str]


class FileDownloadUrlRequest(BaseModel):
    workspace_id: UUID
    storage_key: str = Field(min_length=2, max_length=512)


class FileDownloadUrlResponse(BaseModel):
    download_url: str
    expires_in_seconds: int
