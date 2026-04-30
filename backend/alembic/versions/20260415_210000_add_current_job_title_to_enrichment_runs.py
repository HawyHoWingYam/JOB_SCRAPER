"""add current job title to enrichment runs

Revision ID: 20260415_210000
Revises: 20260415_190000
Create Date: 2026-04-15 21:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260415_210000"
down_revision = "20260415_190000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrichment_runs",
        sa.Column("current_job_title", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_runs", "current_job_title")

