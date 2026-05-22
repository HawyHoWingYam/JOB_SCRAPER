"""add scheduler runtime heartbeats and request payload snapshots

Revision ID: 20260522_120000
Revises: 20260520_130000
Create Date: 2026-05-22 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260522_120000"
down_revision = "20260520_130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "schedule_executions",
        sa.Column("request_payload_snapshot", sa.JSON(), nullable=True),
    )
    op.create_table(
        "scheduler_runtime_heartbeats",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner", sa.String(length=64), nullable=False),
        sa.Column("worker_name", sa.String(length=255), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("active_schedule_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("registered_job_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reconcile_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduler_runtime_heartbeats_last_heartbeat_at",
        "scheduler_runtime_heartbeats",
        ["last_heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scheduler_runtime_heartbeats_last_heartbeat_at",
        table_name="scheduler_runtime_heartbeats",
    )
    op.drop_table("scheduler_runtime_heartbeats")
    op.drop_column("schedule_executions", "request_payload_snapshot")
