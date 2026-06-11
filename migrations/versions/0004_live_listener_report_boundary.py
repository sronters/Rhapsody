from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_live_boundary"
down_revision = "0003_live_meeting_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "live_meeting_sessions",
        sa.Column("stop_requested_at", sa.DateTime(timezone=True)),
    )
    op.add_column("live_meeting_sessions", sa.Column("report_text", sa.Text()))


def downgrade() -> None:
    op.drop_column("live_meeting_sessions", "report_text")
    op.drop_column("live_meeting_sessions", "stop_requested_at")
