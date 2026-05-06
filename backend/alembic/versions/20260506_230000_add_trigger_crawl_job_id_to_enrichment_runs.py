"""add trigger crawl job id to enrichment runs

Revision ID: 20260506_230000
Revises: 20260506_210000
Create Date: 2026-05-06 23:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260506_230000"
down_revision = "20260506_210000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrichment_runs",
        sa.Column("trigger_crawl_job_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_enrichment_runs_trigger_crawl_job_id",
        "enrichment_runs",
        ["trigger_crawl_job_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_enrichment_runs_trigger_crawl_job_id",
        "enrichment_runs",
        "crawl_jobs",
        ["trigger_crawl_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_enrichment_runs_trigger_crawl_job_id",
        "enrichment_runs",
        type_="foreignkey",
    )
    op.drop_index("ix_enrichment_runs_trigger_crawl_job_id", table_name="enrichment_runs")
    op.drop_column("enrichment_runs", "trigger_crawl_job_id")
