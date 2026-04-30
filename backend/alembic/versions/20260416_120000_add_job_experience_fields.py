"""add job experience fields

Revision ID: 20260416_120000
Revises: 20260415_210000
Create Date: 2026-04-16 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260416_120000"
down_revision = "20260415_210000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("experience_min_years", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("experience_max_years", sa.Integer(), nullable=True))
    op.add_column("jobs", sa.Column("experience_level", sa.String(length=50), nullable=True))
    op.add_column("jobs", sa.Column("experience_summary", sa.Text(), nullable=True))
    op.add_column("jobs", sa.Column("experience_evidence", sa.JSON(), nullable=True))

    op.create_index("ix_jobs_experience_min_years", "jobs", ["experience_min_years"], unique=False)
    op.create_index("ix_jobs_experience_max_years", "jobs", ["experience_max_years"], unique=False)
    op.create_index("ix_jobs_experience_level", "jobs", ["experience_level"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_experience_level", table_name="jobs")
    op.drop_index("ix_jobs_experience_max_years", table_name="jobs")
    op.drop_index("ix_jobs_experience_min_years", table_name="jobs")

    op.drop_column("jobs", "experience_evidence")
    op.drop_column("jobs", "experience_summary")
    op.drop_column("jobs", "experience_level")
    op.drop_column("jobs", "experience_max_years")
    op.drop_column("jobs", "experience_min_years")
