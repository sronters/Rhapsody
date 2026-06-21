from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_call_sessions"
down_revision = "0006_project_isolation_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "listener_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=160), nullable=True),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("encrypted_session", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_call_session_id", sa.Uuid(), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("telegram_user_id", name="uq_listener_accounts_telegram_user_id"),
    )

    op.create_table(
        "call_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_group_call_id", sa.String(length=160), nullable=True),
        sa.Column(
            "listener_account_id",
            sa.Uuid(),
            sa.ForeignKey("listener_accounts.id"),
            nullable=True,
        ),
        sa.Column("requested_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "live_meeting_session_id",
            sa.Uuid(),
            sa.ForeignKey("live_meeting_sessions.id"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_audio_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("reconnect_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_call_sessions_workspace_chat_status",
        "call_sessions",
        ["workspace_id", "telegram_chat_id", "status"],
    )
    op.create_index(
        "ix_call_sessions_live_meeting_session_id",
        "call_sessions",
        ["live_meeting_session_id"],
    )

    op.create_table(
        "call_audio_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("call_session_id", sa.Uuid(), sa.ForeignKey("call_sessions.id"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=80), nullable=False),
        sa.Column("local_path", sa.String(length=512), nullable=False),
        sa.Column("object_ref", sa.String(length=512), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("byte_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "call_session_id",
            "sequence_number",
            name="uq_call_audio_chunks_session_sequence",
        ),
    )
    op.create_index(
        "ix_call_audio_chunks_session_status",
        "call_audio_chunks",
        ["call_session_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_call_audio_chunks_session_status", table_name="call_audio_chunks")
    op.drop_table("call_audio_chunks")
    op.drop_index("ix_call_sessions_live_meeting_session_id", table_name="call_sessions")
    op.drop_index("ix_call_sessions_workspace_chat_status", table_name="call_sessions")
    op.drop_table("call_sessions")
    op.drop_table("listener_accounts")
