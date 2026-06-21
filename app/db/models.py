from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class UpdateTimestampMixin:
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    deployment_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="cloud")
    retention_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="standard")
    workspaces: Mapped[list[Workspace]] = relationship(back_populates="organization")


class Workspace(Base, TimestampMixin, UpdateTimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    organization: Mapped[Organization] = relationship(back_populates="workspaces")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320))
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")


class WorkspaceMember(Base, TimestampMixin):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(40), nullable=False)


class TelegramChat(Base):
    __tablename__ = "telegram_chats"
    __table_args__ = (
        UniqueConstraint("workspace_id", "telegram_chat_id", name="uq_workspace_chat"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    selected_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    chat_type: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    title: Mapped[str | None] = mapped_column(String(240))
    locale: Mapped[str] = mapped_column(String(8), nullable=False, default="en")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Meeting(Base, TimestampMixin):
    __tablename__ = "meetings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MeetingSummary(Base, TimestampMixin):
    __tablename__ = "meeting_summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    meeting_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("meetings.id"), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    sender_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    importance: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")


class Document(Base, TimestampMixin):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)


class MemoryChunk(Base, TimestampMixin):
    __tablename__ = "memory_chunks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_title: Mapped[str] = mapped_column(String(240), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(256))


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(320), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Decision(Base, TimestampMixin):
    __tablename__ = "decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(320), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Risk(Base, TimestampMixin):
    __tablename__ = "risks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(320), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    mitigation: Mapped[str | None] = mapped_column(Text)


class LiveMeetingSession(Base, TimestampMixin):
    __tablename__ = "live_meeting_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    started_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stop_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="starting")
    transcript: Mapped[str | None] = mapped_column(Text)
    report_text: Mapped[str | None] = mapped_column(Text)
    audio_object_ref: Mapped[str | None] = mapped_column(String(512))
    error_message: Mapped[str | None] = mapped_column(Text)


class ListenerAccount(Base, TimestampMixin, UpdateTimestampMixin):
    __tablename__ = "listener_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    username: Mapped[str | None] = mapped_column(String(160))
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    encrypted_session: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="AVAILABLE")
    current_call_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CallSession(Base, TimestampMixin, UpdateTimestampMixin):
    __tablename__ = "call_sessions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_group_call_id: Mapped[str | None] = mapped_column(String(160))
    listener_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("listener_accounts.id")
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    live_meeting_session_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("live_meeting_sessions.id")
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="REQUESTED")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_audio_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    reconnect_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CallAudioChunk(Base, TimestampMixin, UpdateTimestampMixin):
    __tablename__ = "call_audio_chunks"
    __table_args__ = (
        UniqueConstraint(
            "call_session_id",
            "sequence_number",
            name="uq_call_audio_chunks_session_sequence",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    call_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("call_sessions.id"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(80), nullable=False, default="audio/wav")
    local_path: Mapped[str] = mapped_column(String(512), nullable=False)
    object_ref: Mapped[str | None] = mapped_column(String(512))
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="SPOOLED")
    transcript: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message: Mapped[str | None] = mapped_column(Text)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class AIRequest(Base, TimestampMixin):
    __tablename__ = "ai_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    purpose: Mapped[str] = mapped_column(String(80), nullable=False)
    prompt_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class EncryptedAPIKey(Base, TimestampMixin):
    __tablename__ = "encrypted_api_keys"
    __table_args__ = (UniqueConstraint("organization_id", "provider", name="uq_org_provider_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workspaces.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
