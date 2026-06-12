from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_project_isolation_metadata"
down_revision = "0005_active_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("workspaces", sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "workspaces",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
    )
    op.add_column(
        "workspaces",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_foreign_key(
        "fk_workspaces_created_by_user_id_users",
        "workspaces",
        "users",
        ["created_by_user_id"],
        ["id"],
    )
    op.alter_column("workspaces", "status", server_default=None)

    op.add_column(
        "workspace_members",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.add_column("telegram_chats", sa.Column("selected_by_user_id", sa.Uuid(), nullable=True))
    op.add_column(
        "telegram_chats",
        sa.Column("chat_type", sa.String(length=32), nullable=False, server_default="private"),
    )
    op.create_foreign_key(
        "fk_telegram_chats_selected_by_user_id_users",
        "telegram_chats",
        "users",
        ["selected_by_user_id"],
        ["id"],
    )
    op.execute(
        """
        UPDATE telegram_chats AS tc
        SET selected_by_user_id = wm.user_id
        FROM workspace_members AS wm
        WHERE tc.workspace_id = wm.workspace_id
          AND tc.telegram_chat_id > 0
          AND (
              SELECT count(*)
              FROM workspace_members AS members
              WHERE members.workspace_id = tc.workspace_id
          ) = 1
        """
    )
    op.execute(
        """
        UPDATE telegram_chats
        SET chat_type = 'group'
        WHERE telegram_chat_id < 0
          AND selected_by_user_id IS NULL
        """
    )
    op.alter_column("telegram_chats", "chat_type", server_default=None)

    op.add_column("documents", sa.Column("uploaded_by_user_id", sa.Uuid(), nullable=True))
    op.add_column("documents", sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True))
    op.add_column("documents", sa.Column("telegram_message_id", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        "fk_documents_uploaded_by_user_id_users",
        "documents",
        "users",
        ["uploaded_by_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_documents_uploaded_by_user_id_users", "documents", type_="foreignkey")
    op.drop_column("documents", "telegram_message_id")
    op.drop_column("documents", "telegram_chat_id")
    op.drop_column("documents", "uploaded_by_user_id")

    op.drop_constraint(
        "fk_telegram_chats_selected_by_user_id_users",
        "telegram_chats",
        type_="foreignkey",
    )
    op.drop_column("telegram_chats", "chat_type")
    op.drop_column("telegram_chats", "selected_by_user_id")

    op.drop_column("workspace_members", "created_at")

    op.drop_constraint("fk_workspaces_created_by_user_id_users", "workspaces", type_="foreignkey")
    op.drop_column("workspaces", "updated_at")
    op.drop_column("workspaces", "status")
    op.drop_column("workspaces", "created_by_user_id")
    op.drop_column("workspaces", "description")
