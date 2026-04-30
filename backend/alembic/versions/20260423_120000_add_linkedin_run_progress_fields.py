"""add linkedin run progress fields

Revision ID: 20260423_120000
Revises: 20260421_210000
Create Date: 2026-04-23 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_120000"
down_revision = "20260421_210000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("linkedin_task_runs", sa.Column("progress_stage", sa.String(length=100), nullable=True))
    op.add_column("linkedin_task_runs", sa.Column("total_candidates", sa.Integer(), nullable=True))
    op.add_column(
        "linkedin_task_runs",
        sa.Column("processed_candidates", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("linkedin_task_runs", sa.Column("current_job_title", sa.String(length=255), nullable=True))
    op.add_column("linkedin_task_runs", sa.Column("progress_updated_at", sa.DateTime(), nullable=True))
    op.alter_column("linkedin_task_runs", "processed_candidates", server_default=None)


def downgrade() -> None:
    op.drop_column("linkedin_task_runs", "progress_updated_at")
    op.drop_column("linkedin_task_runs", "current_job_title")
    op.drop_column("linkedin_task_runs", "processed_candidates")
    op.drop_column("linkedin_task_runs", "total_candidates")
    op.drop_column("linkedin_task_runs", "progress_stage")
