"""add source-specific scraper pacing settings

Revision ID: 20260716_180000
Revises: 20260716_120000
Create Date: 2026-07-16 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from datetime import datetime


revision = "20260716_180000"
down_revision = "20260716_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    table = op.create_table(
        "scraper_pacing_settings",
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("interval_min_seconds", sa.Float(), nullable=False),
        sa.Column("interval_max_seconds", sa.Float(), nullable=False),
        sa.Column("burst_size", sa.Integer(), nullable=False),
        sa.Column("burst_pause_seconds", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "interval_min_seconds >= 0.1 AND interval_min_seconds <= 60",
            name="ck_scraper_pacing_interval_min",
        ),
        sa.CheckConstraint(
            "interval_max_seconds >= 0.1 AND interval_max_seconds <= 60",
            name="ck_scraper_pacing_interval_max",
        ),
        sa.CheckConstraint(
            "interval_min_seconds <= interval_max_seconds",
            name="ck_scraper_pacing_interval_order",
        ),
        sa.CheckConstraint(
            "burst_size >= 1 AND burst_size <= 1000",
            name="ck_scraper_pacing_burst_size",
        ),
        sa.CheckConstraint(
            "burst_pause_seconds >= 0 AND burst_pause_seconds <= 3600",
            name="ck_scraper_pacing_burst_pause",
        ),
        sa.PrimaryKeyConstraint("source_site"),
    )
    op.bulk_insert(
        table,
        [
            {
                "source_site": source,
                "interval_min_seconds": 1.0,
                "interval_max_seconds": 3.0,
                "burst_size": 20,
                "burst_pause_seconds": 30.0,
                "updated_at": datetime.utcnow(),
            }
            for source in ("jobsdb", "ctgoodjobs", "offertoday")
        ],
    )


def downgrade() -> None:
    op.drop_table("scraper_pacing_settings")
