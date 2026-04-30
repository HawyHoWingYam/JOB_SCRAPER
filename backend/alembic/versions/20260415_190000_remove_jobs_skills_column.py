"""remove legacy jobs skills column

Revision ID: 20260415_190000
Revises: 20260415_163000
Create Date: 2026-04-15 19:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260415_190000"
down_revision = "20260415_163000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("jobs", "skills")


def downgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("skills", postgresql.ARRAY(sa.String()), nullable=True),
    )
