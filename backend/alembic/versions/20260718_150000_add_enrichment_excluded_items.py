"""add excluded item tracking to enrichment runs

Revision ID: 20260718_150000
Revises: 20260718_120000
Create Date: 2026-07-18 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_150000"
down_revision = "20260718_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrichment_runs",
        sa.Column("excluded_items", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("enrichment_runs", "excluded_items")
