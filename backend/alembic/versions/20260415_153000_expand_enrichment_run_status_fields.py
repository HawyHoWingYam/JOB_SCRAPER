"""expand enrichment run status fields

Revision ID: 20260415_153000
Revises: 20260415_103800
Create Date: 2026-04-15 15:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260415_153000"
down_revision = "20260415_103800"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrichment_runs",
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
    )
    op.add_column(
        "enrichment_runs",
        sa.Column("started_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "enrichment_runs",
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "enrichment_runs",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_enrichment_runs_status",
        "enrichment_runs",
        ["status"],
        unique=False,
    )
    op.alter_column("enrichment_runs", "status", server_default=None)

    op.add_column(
        "enrichment_run_items",
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "enrichment_run_items",
        sa.Column("started_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "enrichment_run_items",
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("enrichment_run_items", "completed_at")
    op.drop_column("enrichment_run_items", "started_at")
    op.drop_column("enrichment_run_items", "error_message")

    op.drop_index("ix_enrichment_runs_status", table_name="enrichment_runs")
    op.drop_column("enrichment_runs", "error_message")
    op.drop_column("enrichment_runs", "completed_at")
    op.drop_column("enrichment_runs", "started_at")
    op.drop_column("enrichment_runs", "status")
