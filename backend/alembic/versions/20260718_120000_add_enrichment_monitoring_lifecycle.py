"""add enrichment monitoring lifecycle

Revision ID: 20260718_120000
Revises: 20260716_180000
Create Date: 2026-07-18 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260718_120000"
down_revision = "20260716_180000"
branch_labels = None
depends_on = None


_ACTIVE_STATUSES = "'pending', 'running', 'stopping'"


def _reconcile_duplicate_active_runs() -> None:
    op.execute(
        f"""
        WITH ranked_active AS (
            SELECT id,
                   row_number() OVER (
                       ORDER BY COALESCE(started_at, created_at) DESC,
                                created_at DESC,
                                id DESC
                   ) AS active_rank
            FROM enrichment_runs
            WHERE status IN ({_ACTIVE_STATUSES})
        ), duplicate_active AS (
            SELECT id
            FROM ranked_active
            WHERE active_rank > 1
        )
        UPDATE enrichment_run_items
        SET status = 'failed',
            error_message = 'Recovered duplicate active run before single-active enforcement',
            started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP)
        WHERE run_id IN (SELECT id FROM duplicate_active)
          AND status IN ('pending', 'running')
        """
    )
    op.execute(
        f"""
        WITH ranked_active AS (
            SELECT id,
                   row_number() OVER (
                       ORDER BY COALESCE(started_at, created_at) DESC,
                                created_at DESC,
                                id DESC
                   ) AS active_rank
            FROM enrichment_runs
            WHERE status IN ({_ACTIVE_STATUSES})
        )
        UPDATE enrichment_runs
        SET status = CASE WHEN completed_items > 0 THEN 'completed_with_failures' ELSE 'failed' END,
            pending_items = 0,
            failed_items = GREATEST(failed_items, total_items - completed_items),
            completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP),
            current_job_title = NULL,
            error_message = 'Recovered duplicate active run before single-active enforcement'
        WHERE id IN (SELECT id FROM ranked_active WHERE active_rank > 1)
        """
    )


def upgrade() -> None:
    op.add_column(
        "enrichment_runs",
        sa.Column("cancelled_items", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "enrichment_runs",
        sa.Column("stop_requested_at", sa.DateTime(), nullable=True),
    )
    _reconcile_duplicate_active_runs()
    op.execute(
        f"""
        CREATE UNIQUE INDEX ux_enrichment_runs_one_active
        ON enrichment_runs ((1))
        WHERE status IN ({_ACTIVE_STATUSES})
        """
    )


def downgrade() -> None:
    op.drop_index("ux_enrichment_runs_one_active", table_name="enrichment_runs")
    op.drop_column("enrichment_runs", "stop_requested_at")
    op.drop_column("enrichment_runs", "cancelled_items")
