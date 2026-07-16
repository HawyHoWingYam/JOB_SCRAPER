"""add durable crawl job execution ownership

Revision ID: 20260716_120000
Revises: 20260602_114500
Create Date: 2026-07-16 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260716_120000"
down_revision = "20260602_114500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_job_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generation", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("launcher_instance_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=True),
        sa.Column("process_create_time", sa.Float(), nullable=True),
        sa.Column("command", sa.JSON(), nullable=False),
        sa.Column("launched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["crawl_job_id"], ["crawl_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("generation"),
    )
    op.create_index(
        "ix_crawl_job_executions_crawl_job_id",
        "crawl_job_executions",
        ["crawl_job_id"],
    )
    op.create_index(
        "ix_crawl_job_executions_generation",
        "crawl_job_executions",
        ["generation"],
        unique=True,
    )
    op.create_index(
        "ix_crawl_job_executions_status",
        "crawl_job_executions",
        ["status"],
    )
    op.create_index(
        "ix_crawl_job_executions_job_status_created",
        "crawl_job_executions",
        ["crawl_job_id", "status", "created_at"],
    )
    op.create_index(
        "ix_crawl_job_executions_status_stop_requested",
        "crawl_job_executions",
        ["status", "stop_requested_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crawl_job_executions_status_stop_requested",
        table_name="crawl_job_executions",
    )
    op.drop_index(
        "ix_crawl_job_executions_job_status_created",
        table_name="crawl_job_executions",
    )
    op.drop_index("ix_crawl_job_executions_status", table_name="crawl_job_executions")
    op.drop_index(
        "ix_crawl_job_executions_generation", table_name="crawl_job_executions"
    )
    op.drop_index(
        "ix_crawl_job_executions_crawl_job_id", table_name="crawl_job_executions"
    )
    op.drop_table("crawl_job_executions")
