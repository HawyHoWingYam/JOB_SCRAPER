"""add company enrichment run tables

Revision ID: 20260419_123000
Revises: 20260416_120000
Create Date: 2026-04-19 12:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260419_123000"
down_revision = "20260416_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_enrichment_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("pending_items", sa.Integer(), nullable=False),
        sa.Column("completed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("current_company_name", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_enrichment_runs_status",
        "company_enrichment_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_company_enrichment_runs_created_at",
        "company_enrichment_runs",
        ["created_at"],
        unique=False,
    )

    op.create_table(
        "company_enrichment_run_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["company_enrichment_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_enrichment_run_items_run_id",
        "company_enrichment_run_items",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_company_enrichment_run_items_company_id",
        "company_enrichment_run_items",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_company_enrichment_run_items_created_at",
        "company_enrichment_run_items",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_company_enrichment_run_items_created_at", table_name="company_enrichment_run_items")
    op.drop_index("ix_company_enrichment_run_items_company_id", table_name="company_enrichment_run_items")
    op.drop_index("ix_company_enrichment_run_items_run_id", table_name="company_enrichment_run_items")
    op.drop_table("company_enrichment_run_items")

    op.drop_index("ix_company_enrichment_runs_created_at", table_name="company_enrichment_runs")
    op.drop_index("ix_company_enrichment_runs_status", table_name="company_enrichment_runs")
    op.drop_table("company_enrichment_runs")
