"""add enrichment run tables

Revision ID: 20260415_103800
Revises:
Create Date: 2026-04-15 10:38:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260415_103800"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enrichment_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("job_ids", sa.JSON(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("pending_items", sa.Integer(), nullable=False),
        sa.Column("completed_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_enrichment_runs_created_at",
        "enrichment_runs",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_enrichment_runs_source_type",
        "enrichment_runs",
        ["source_type"],
        unique=False,
    )

    op.create_table(
        "enrichment_run_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["enrichment_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_enrichment_run_items_created_at",
        "enrichment_run_items",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "ix_enrichment_run_items_job_id",
        "enrichment_run_items",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_enrichment_run_items_run_id",
        "enrichment_run_items",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_enrichment_run_items_run_id", table_name="enrichment_run_items")
    op.drop_index("ix_enrichment_run_items_job_id", table_name="enrichment_run_items")
    op.drop_index("ix_enrichment_run_items_created_at", table_name="enrichment_run_items")
    op.drop_table("enrichment_run_items")

    op.drop_index("ix_enrichment_runs_source_type", table_name="enrichment_runs")
    op.drop_index("ix_enrichment_runs_created_at", table_name="enrichment_runs")
    op.drop_table("enrichment_runs")
