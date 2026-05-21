"""add schedule crawl phase and detail limit

Revision ID: 20260520_130000
Revises: 20260520_120000
Create Date: 2026-05-20 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "20260520_130000"
down_revision = "20260520_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scrape_schedules",
        sa.Column("crawl_phase", sa.String(length=32), nullable=False, server_default="listing"),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("detail_limit", sa.Integer(), nullable=False, server_default="100"),
    )
    op.create_index("ix_scrape_schedules_crawl_phase", "scrape_schedules", ["crawl_phase"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_scrape_schedules_crawl_phase", table_name="scrape_schedules")
    op.drop_column("scrape_schedules", "detail_limit")
    op.drop_column("scrape_schedules", "crawl_phase")
