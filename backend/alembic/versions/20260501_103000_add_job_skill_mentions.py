"""add job skill mentions

Revision ID: 20260501_103000
Revises: 20260430_140000
Create Date: 2026-05-01 10:30:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260501_103000"
down_revision = "20260430_140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_skill_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_name", sa.String(length=100), nullable=False),
        sa.Column("normalized_name", sa.String(length=100), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generic_tag", sa.String(length=100), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["review_candidate_id"],
            ["skill_review_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_skill_mentions_job_id", "job_skill_mentions", ["job_id"], unique=False)
    op.create_index(
        "ix_job_skill_mentions_normalized_name",
        "job_skill_mentions",
        ["normalized_name"],
        unique=False,
    )
    op.create_index(
        "ix_job_skill_mentions_resolution",
        "job_skill_mentions",
        ["resolution"],
        unique=False,
    )
    op.create_index(
        "ix_job_skill_mentions_review_candidate_id",
        "job_skill_mentions",
        ["review_candidate_id"],
        unique=False,
    )
    op.create_index("ix_job_skill_mentions_skill_id", "job_skill_mentions", ["skill_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_skill_mentions_skill_id", table_name="job_skill_mentions")
    op.drop_index(
        "ix_job_skill_mentions_review_candidate_id",
        table_name="job_skill_mentions",
    )
    op.drop_index("ix_job_skill_mentions_resolution", table_name="job_skill_mentions")
    op.drop_index(
        "ix_job_skill_mentions_normalized_name",
        table_name="job_skill_mentions",
    )
    op.drop_index("ix_job_skill_mentions_job_id", table_name="job_skill_mentions")
    op.drop_table("job_skill_mentions")
