from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_locales"
down_revision = "0007_call_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("locale", sa.String(length=8), nullable=False, server_default="en"),
    )
    op.add_column(
        "telegram_chats",
        sa.Column("locale", sa.String(length=8), nullable=False, server_default="en"),
    )


def downgrade() -> None:
    op.drop_column("telegram_chats", "locale")
    op.drop_column("users", "locale")
