from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_active_projects"
down_revision = "0004_live_boundary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telegram_chats",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("telegram_chats", "is_active", server_default=None)


def downgrade() -> None:
    op.drop_column("telegram_chats", "is_active")
