"""add source site to jobs and schedules

Revision ID: 20260420_120000
Revises: 20260419_123000
Create Date: 2026-04-20 12:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260420_120000"
down_revision = "20260419_123000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column(
            "source_site",
            sa.String(length=32),
            nullable=True,
            server_default=sa.text("'jobsdb'"),
        ),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column(
            "source_site",
            sa.String(length=32),
            nullable=True,
            server_default=sa.text("'jobsdb'"),
        ),
    )

    # Backfill existing rows.
    op.execute("UPDATE jobs SET source_site = 'jobsdb' WHERE source_site IS NULL")
    op.execute("UPDATE scrape_schedules SET source_site = 'jobsdb' WHERE source_site IS NULL")

    # Make non-null going forward (after backfill).
    op.alter_column("jobs", "source_site", nullable=False, server_default=sa.text("'jobsdb'"))
    op.alter_column("scrape_schedules", "source_site", nullable=False, server_default=sa.text("'jobsdb'"))

    ctx = op.get_context()
    if ctx.dialect.name == "postgresql":
        # Concurrent index creation avoids blocking writes in production, but
        # requires running outside the migration transaction.
        with ctx.autocommit_block():
            op.create_index(
                "ix_jobs_source_site",
                "jobs",
                ["source_site"],
                unique=False,
                postgresql_concurrently=True,
            )
            op.create_index(
                "ix_scrape_schedules_source_site",
                "scrape_schedules",
                ["source_site"],
                unique=False,
                postgresql_concurrently=True,
            )
    else:
        op.create_index("ix_jobs_source_site", "jobs", ["source_site"], unique=False)
        op.create_index("ix_scrape_schedules_source_site", "scrape_schedules", ["source_site"], unique=False)


def downgrade() -> None:
    ctx = op.get_context()
    if ctx.dialect.name == "postgresql":
        with ctx.autocommit_block():
            op.drop_index(
                "ix_scrape_schedules_source_site",
                table_name="scrape_schedules",
                postgresql_concurrently=True,
            )
            op.drop_index(
                "ix_jobs_source_site",
                table_name="jobs",
                postgresql_concurrently=True,
            )
    else:
        op.drop_index("ix_scrape_schedules_source_site", table_name="scrape_schedules")
        op.drop_index("ix_jobs_source_site", table_name="jobs")
    op.drop_column("scrape_schedules", "source_site")
    op.drop_column("jobs", "source_site")
