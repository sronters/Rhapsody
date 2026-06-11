from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_live_meeting_sessions"
down_revision = "0002_memory_embedding_vector"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "live_meeting_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("started_by_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("transcript", sa.Text()),
        sa.Column("audio_object_ref", sa.String(length=512)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_live_meeting_sessions_workspace_status",
        "live_meeting_sessions",
        ["workspace_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_live_meeting_sessions_workspace_status", table_name="live_meeting_sessions")
    op.drop_table("live_meeting_sessions")
