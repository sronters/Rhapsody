from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class MemoryQuestion(BaseModel):
    workspace_id: UUID
    question: str = Field(min_length=3, max_length=4000)
    top_k: int = Field(default=6, ge=1, le=20)


class MemorySource(BaseModel):
    id: UUID
    source_type: str
    source_title: str
    source_url: str | None = None
    excerpt: str


class MemoryAnswer(BaseModel):
    answer: str
    sources: list[MemorySource]
