"""drop linkedin runtime tables

Revision ID: 20260428_120000
Revises: 20260423_120000
Create Date: 2026-04-28 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260428_120000"
down_revision = "20260423_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(
        "ux_linkedin_connection_flows_one_non_terminal",
        table_name="linkedin_connection_flows",
    )
    op.drop_index("ix_linkedin_connection_flows_status", table_name="linkedin_connection_flows")
    op.drop_table("linkedin_connection_flows")

    op.drop_index("ix_linkedin_task_runs_started_at", table_name="linkedin_task_runs")
    op.drop_index("ix_linkedin_task_runs_task_id", table_name="linkedin_task_runs")
    op.drop_index("ix_linkedin_task_runs_status", table_name="linkedin_task_runs")
    op.drop_table("linkedin_task_runs")

    op.drop_index("ix_linkedin_search_tasks_session_profile_id", table_name="linkedin_search_tasks")
    op.drop_index("ix_linkedin_search_tasks_is_active", table_name="linkedin_search_tasks")
    op.drop_table("linkedin_search_tasks")

    op.drop_index("ix_linkedin_session_profiles_is_active", table_name="linkedin_session_profiles")
    op.drop_table("linkedin_session_profiles")


def downgrade() -> None:
    op.create_table(
        "linkedin_session_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("storage_state_path", sa.String(length=1024), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("last_validation_status", sa.String(length=50), nullable=False, server_default="unknown"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        "ix_linkedin_session_profiles_is_active",
        "linkedin_session_profiles",
        ["is_active"],
        unique=False,
    )

    op.create_table(
        "linkedin_search_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("keywords", sa.String(length=500), nullable=False),
        sa.Column("location", sa.String(length=255), nullable=False),
        sa.Column("date_window", sa.String(length=50), nullable=False),
        sa.Column("optional_filters", sa.JSON(), nullable=False),
        sa.Column("cron_expression", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=50), nullable=False),
        sa.Column("max_pages", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_profile_id"], ["linkedin_session_profiles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_linkedin_search_tasks_is_active",
        "linkedin_search_tasks",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        "ix_linkedin_search_tasks_session_profile_id",
        "linkedin_search_tasks",
        ["session_profile_id"],
        unique=False,
    )

    op.create_table(
        "linkedin_task_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("jobs_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_jobs_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("details_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_saved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("jobs_enriched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("stop_reason", sa.String(length=100), nullable=True),
        sa.Column("run_metadata", sa.JSON(), nullable=True),
        sa.Column("progress_stage", sa.String(length=100), nullable=True),
        sa.Column("total_candidates", sa.Integer(), nullable=True),
        sa.Column("processed_candidates", sa.Integer(), nullable=False),
        sa.Column("current_job_title", sa.String(length=255), nullable=True),
        sa.Column("progress_updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["linkedin_search_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_linkedin_task_runs_status", "linkedin_task_runs", ["status"], unique=False)
    op.create_index("ix_linkedin_task_runs_task_id", "linkedin_task_runs", ["task_id"], unique=False)
    op.create_index("ix_linkedin_task_runs_started_at", "linkedin_task_runs", ["started_at"], unique=False)

    op.create_table(
        "linkedin_connection_flows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="pending"),
        sa.Column("flow_token_hash", sa.String(length=128), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("storage_state_target", sa.String(length=1024), nullable=False),
        sa.Column("helper_timeout_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_linkedin_connection_flows_status",
        "linkedin_connection_flows",
        ["status"],
        unique=False,
    )
    op.execute(
        """
        CREATE UNIQUE INDEX ux_linkedin_connection_flows_one_non_terminal
        ON linkedin_connection_flows ((1))
        WHERE status IN ('pending', 'waiting_for_browser', 'waiting_for_login', 'saving_session')
        """
    )
