"""add crawl job listings staging table

Revision ID: 20260520_120000
Revises: 20260506_230000
Create Date: 2026-05-20 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260520_120000"
down_revision = "20260506_230000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_job_listings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("source_job_id", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=1024), nullable=False),
        sa.Column("source_classification_id", sa.String(length=50), nullable=True),
        sa.Column("source_classification_name", sa.String(length=255), nullable=True),
        sa.Column("listing_page", sa.Integer(), nullable=True),
        sa.Column("listing_rank", sa.Integer(), nullable=True),
        sa.Column("listing_payload", sa.JSON(), nullable=False),
        sa.Column("detail_payload", sa.JSON(), nullable=True),
        sa.Column("detail_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("detail_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_detail_crawl_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("detail_error_message", sa.Text(), nullable=True),
        sa.Column("detail_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "crawl_job_id",
            "source_site",
            "source_job_id",
            name="uq_crawl_job_listings_job_source_key",
        ),
    )
    op.create_index("ix_crawl_job_listings_id", "crawl_job_listings", ["id"], unique=False)
    op.create_index("ix_crawl_job_listings_crawl_job_id", "crawl_job_listings", ["crawl_job_id"], unique=False)
    op.create_index("ix_crawl_job_listings_source_site", "crawl_job_listings", ["source_site"], unique=False)
    op.create_index("ix_crawl_job_listings_source_job_id", "crawl_job_listings", ["source_job_id"], unique=False)
    op.create_index(
        "ix_crawl_job_listings_source_classification_id",
        "crawl_job_listings",
        ["source_classification_id"],
        unique=False,
    )
    op.create_index("ix_crawl_job_listings_detail_status", "crawl_job_listings", ["detail_status"], unique=False)
    op.create_index(
        "ix_crawl_job_listings_last_detail_crawl_job_id",
        "crawl_job_listings",
        ["last_detail_crawl_job_id"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_job_listings_published_job_id",
        "crawl_job_listings",
        ["published_job_id"],
        unique=False,
    )
    op.create_index("ix_crawl_job_listings_created_at", "crawl_job_listings", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_crawl_job_listings_created_at", table_name="crawl_job_listings")
    op.drop_index("ix_crawl_job_listings_published_job_id", table_name="crawl_job_listings")
    op.drop_index("ix_crawl_job_listings_last_detail_crawl_job_id", table_name="crawl_job_listings")
    op.drop_index("ix_crawl_job_listings_detail_status", table_name="crawl_job_listings")
    op.drop_index("ix_crawl_job_listings_source_classification_id", table_name="crawl_job_listings")
    op.drop_index("ix_crawl_job_listings_source_job_id", table_name="crawl_job_listings")
    op.drop_index("ix_crawl_job_listings_source_site", table_name="crawl_job_listings")
    op.drop_index("ix_crawl_job_listings_crawl_job_id", table_name="crawl_job_listings")
    op.drop_index("ix_crawl_job_listings_id", table_name="crawl_job_listings")
    op.drop_table("crawl_job_listings")
