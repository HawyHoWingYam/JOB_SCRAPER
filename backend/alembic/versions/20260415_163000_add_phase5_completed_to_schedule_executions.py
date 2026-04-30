"""add phase5 completed to schedule executions

Revision ID: 20260415_163000
Revises: 20260415_153000
Create Date: 2026-04-15 16:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260415_163000"
down_revision = "20260415_153000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedule_executions",
        sa.Column("phase5_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("schedule_executions", "phase5_completed", server_default=None)


def downgrade() -> None:
    op.drop_column("schedule_executions", "phase5_completed")
