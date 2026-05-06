"""add event backbone and pgvector

Revision ID: 20260506_120000
Revises: 20260504_170000
Create Date: 2026-05-06 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


revision = "20260506_120000"
down_revision = "20260504_170000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "crawl_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False),
        sa.Column("schedule_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["schedule_id"], ["scrape_schedules.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_jobs_id", "crawl_jobs", ["id"], unique=False)
    op.create_index("ix_crawl_jobs_source_site", "crawl_jobs", ["source_site"], unique=False)
    op.create_index("ix_crawl_jobs_schedule_id", "crawl_jobs", ["schedule_id"], unique=False)
    op.create_index("ix_crawl_jobs_status", "crawl_jobs", ["status"], unique=False)
    op.create_index("ix_crawl_jobs_queued_at", "crawl_jobs", ["queued_at"], unique=False)
    op.create_index("ix_crawl_jobs_created_at", "crawl_jobs", ["created_at"], unique=False)

    op.create_table(
        "crawl_job_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("emitted_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["crawl_job_id"], ["crawl_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crawl_job_events_crawl_job_id", "crawl_job_events", ["crawl_job_id"], unique=False)
    op.create_index("ix_crawl_job_events_created_at", "crawl_job_events", ["created_at"], unique=False)

    op.create_table(
        "event_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("topic", sa.String(length=100), nullable=False),
        sa.Column("aggregate_type", sa.String(length=100), nullable=False),
        sa.Column("aggregate_id", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_event_outbox_aggregate_id", "event_outbox", ["aggregate_id"], unique=False)
    op.create_index("ix_event_outbox_status", "event_outbox", ["status"], unique=False)
    op.create_index("ix_event_outbox_available_at", "event_outbox", ["available_at"], unique=False)
    op.create_index("ix_event_outbox_created_at", "event_outbox", ["created_at"], unique=False)

    op.create_table(
        "job_embeddings",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("embedding_model", sa.String(length=255), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False, server_default="384"),
        sa.Column("embedding_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("document_text", sa.Text(), nullable=False),
        sa.Column("document_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("job_id"),
    )
    op.create_index("ix_job_embeddings_document_hash", "job_embeddings", ["document_hash"], unique=False)
    op.execute(
        "CREATE INDEX ix_job_embeddings_embedding_hnsw "
        "ON job_embeddings USING hnsw (embedding vector_cosine_ops)"
    )

    op.add_column("schedule_executions", sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_schedule_executions_crawl_job_id", "schedule_executions", ["crawl_job_id"], unique=False)
    op.create_foreign_key(
        "fk_schedule_executions_crawl_job_id_crawl_jobs",
        "schedule_executions",
        "crawl_jobs",
        ["crawl_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_schedule_executions_crawl_job_id_crawl_jobs",
        "schedule_executions",
        type_="foreignkey",
    )
    op.drop_index("ix_schedule_executions_crawl_job_id", table_name="schedule_executions")
    op.drop_column("schedule_executions", "crawl_job_id")

    op.execute("DROP INDEX IF EXISTS ix_job_embeddings_embedding_hnsw")
    op.drop_index("ix_job_embeddings_document_hash", table_name="job_embeddings")
    op.drop_table("job_embeddings")

    op.drop_index("ix_event_outbox_created_at", table_name="event_outbox")
    op.drop_index("ix_event_outbox_available_at", table_name="event_outbox")
    op.drop_index("ix_event_outbox_status", table_name="event_outbox")
    op.drop_index("ix_event_outbox_aggregate_id", table_name="event_outbox")
    op.drop_table("event_outbox")

    op.drop_index("ix_crawl_job_events_created_at", table_name="crawl_job_events")
    op.drop_index("ix_crawl_job_events_crawl_job_id", table_name="crawl_job_events")
    op.drop_table("crawl_job_events")

    op.drop_index("ix_crawl_jobs_created_at", table_name="crawl_jobs")
    op.drop_index("ix_crawl_jobs_queued_at", table_name="crawl_jobs")
    op.drop_index("ix_crawl_jobs_status", table_name="crawl_jobs")
    op.drop_index("ix_crawl_jobs_schedule_id", table_name="crawl_jobs")
    op.drop_index("ix_crawl_jobs_source_site", table_name="crawl_jobs")
    op.drop_index("ix_crawl_jobs_id", table_name="crawl_jobs")
    op.drop_table("crawl_jobs")
