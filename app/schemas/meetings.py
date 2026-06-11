from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class MeetingIngestRequest(BaseModel):
    workspace_id: UUID
    title: str = Field(min_length=2, max_length=240)
    source: str = Field(default="telegram", pattern="^(telegram|zoom|meet|teams|upload)$")
    transcript_text: str | None = Field(default=None, max_length=200_000)
    media_storage_key: str | None = Field(default=None, max_length=512)
    started_at: datetime | None = None


class MeetingIngestResponse(BaseModel):
    meeting_id: UUID
    status: str


class ExtractedTask(BaseModel):
    title: str
    assignee_hint: str | None = None
    due_hint: str | None = None


class MeetingIntelligence(BaseModel):
    summary: str
    topics: list[str]
    decisions: list[str]
    tasks: list[ExtractedTask]
    risks: list[str]
    follow_up: str
