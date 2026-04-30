"""add linkedin connection flows

Revision ID: 20260421_210000
Revises: 20260421_150000
Create Date: 2026-04-21 21:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260421_210000"
down_revision = "20260421_150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_index(
        "ux_linkedin_connection_flows_one_non_terminal",
        table_name="linkedin_connection_flows",
    )
    op.drop_index("ix_linkedin_connection_flows_status", table_name="linkedin_connection_flows")
    op.drop_table("linkedin_connection_flows")
