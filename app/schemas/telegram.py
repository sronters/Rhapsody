from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class TelegramEvent(BaseModel):
    workspace_id: UUID
    telegram_chat_id: int
    telegram_message_id: int | None = None
    sender_telegram_user_id: int | None = None
    sender_display_name: str = Field(default="Unknown", max_length=160)
    text: str | None = Field(default=None, max_length=20_000)
    file_storage_key: str | None = Field(default=None, max_length=512)
    event_type: str = Field(pattern="^(message|voice|document|command)$")


class TelegramEventAccepted(BaseModel):
    event_id: UUID
    status: str
