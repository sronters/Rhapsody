from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def created_at_column() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        nullable=False,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "organizations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("deployment_mode", sa.String(length=24), nullable=False),
        sa.Column("retention_mode", sa.String(length=24), nullable=False),
        created_at_column(),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        created_at_column(),
    )
    op.create_index("ix_workspaces_org", "workspaces", ["organization_id"])
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), unique=True),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=320)),
        created_at_column(),
    )
    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_member"),
    )
    op.create_table(
        "telegram_chats",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=240)),
        sa.UniqueConstraint("workspace_id", "telegram_chat_id", name="uq_workspace_chat"),
    )
    op.create_table(
        "meetings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        created_at_column(),
    )
    op.create_index("ix_meetings_workspace", "meetings", ["workspace_id"])
    op.create_table(
        "meeting_summaries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("meeting_id", sa.Uuid(), sa.ForeignKey("meetings.id"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("topics", sa.JSON(), nullable=False),
        created_at_column(),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("sender_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("importance", sa.String(length=32), nullable=False),
        created_at_column(),
    )
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        created_at_column(),
    )
    op.create_table(
        "memory_chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source_title", sa.String(length=240), nullable=False),
        sa.Column("source_url", sa.String(length=512)),
        sa.Column("embedding", Vector(256)),
        created_at_column(),
    )
    op.create_index("ix_memory_chunks_workspace", "memory_chunks", ["workspace_id"])
    op.create_index(
        "ix_memory_chunks_embedding_hnsw",
        "memory_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_table(
        "tasks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("title", sa.String(length=320), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("assignee_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.Uuid()),
        created_at_column(),
    )
    op.create_table(
        "decisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("title", sa.String(length=320), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.Uuid()),
        created_at_column(),
    )
    op.create_table(
        "risks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("title", sa.String(length=320), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("mitigation", sa.Text()),
        created_at_column(),
    )
    op.create_table(
        "ai_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("purpose", sa.String(length=80), nullable=False),
        sa.Column("prompt_hash", sa.String(length=64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        created_at_column(),
    )
    op.create_table(
        "encrypted_api_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        created_at_column(),
        sa.UniqueConstraint("organization_id", "provider", name="uq_org_provider_key"),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("organization_id", sa.Uuid(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), sa.ForeignKey("workspaces.id")),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id")),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.Uuid()),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        created_at_column(),
    )


def downgrade() -> None:
    for table in [
        "audit_logs",
        "encrypted_api_keys",
        "ai_requests",
        "risks",
        "decisions",
        "tasks",
        "memory_chunks",
        "documents",
        "messages",
        "meeting_summaries",
        "meetings",
        "telegram_chats",
        "workspace_members",
        "users",
        "workspaces",
        "organizations",
    ]:
        op.drop_table(table)
