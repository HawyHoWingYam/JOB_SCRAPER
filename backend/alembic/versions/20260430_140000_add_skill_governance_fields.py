"""add skill governance fields

Revision ID: 20260430_140000
Revises: 20260428_120000
Create Date: 2026-04-30 14:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260430_140000"
down_revision = "20260428_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("ai_generic_tags", sa.JSON(), nullable=True))

    op.create_table(
        "skill_review_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("suggested_category", sa.String(length=100), nullable=True),
        sa.Column("suggested_technology", sa.String(length=100), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_seen_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_seen_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["first_seen_job_id"], ["jobs.id"]),
        sa.ForeignKeyConstraint(["last_seen_job_id"], ["jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name"),
    )
    op.create_index(
        "ix_skill_review_candidates_normalized_name",
        "skill_review_candidates",
        ["normalized_name"],
        unique=True,
    )
    op.create_index(
        "ix_skill_review_candidates_status",
        "skill_review_candidates",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_skill_review_candidates_status", table_name="skill_review_candidates")
    op.drop_index(
        "ix_skill_review_candidates_normalized_name",
        table_name="skill_review_candidates",
    )
    op.drop_table("skill_review_candidates")
    op.drop_column("jobs", "ai_generic_tags")
