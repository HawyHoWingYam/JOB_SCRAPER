"""add bounded Canonical Taxonomy recovery metadata

Revision ID: 20260722_120000
Revises: 20260720_210000
Create Date: 2026-07-22 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260722_120000"
down_revision = "20260720_210000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrichment_runs",
        sa.Column("run_snapshot", sa.JSON(), nullable=True),
    )
    op.add_column(
        "enrichment_run_items",
        sa.Column("error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "enrichment_run_items",
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("enrichment_run_items", "attempt_count")
    op.drop_column("enrichment_run_items", "error_code")
    op.drop_column("enrichment_runs", "run_snapshot")
