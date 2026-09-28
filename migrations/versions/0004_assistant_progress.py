"""Persist real assistant stage events without changing task data."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "workflow_runs",
        sa.Column("progress_events", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade():
    op.drop_column("workflow_runs", "progress_events")
