"""refine crawl job sequencing and embedding dimensions

Revision ID: 20260506_150000
Revises: 20260506_120000
Create Date: 2026-05-06 15:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "20260506_150000"
down_revision = "20260506_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_crawl_job_events_job_sequence",
        "crawl_job_events",
        ["crawl_job_id", "sequence_no"],
    )

    op.execute("UPDATE job_embeddings SET embedding_dimensions = 384")
    op.create_check_constraint(
        "ck_job_embeddings_dimensions_384",
        "job_embeddings",
        "embedding_dimensions = 384",
    )
    op.alter_column(
        "job_embeddings",
        "embedding_dimensions",
        existing_type=sa.Integer(),
        server_default="384",
        existing_nullable=False,
    )
    op.alter_column(
        "job_embeddings",
        "embedding",
        existing_type=Vector(),
        type_=Vector(384),
        postgresql_using="embedding::vector(384)",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "job_embeddings",
        "embedding",
        existing_type=Vector(384),
        type_=Vector(),
        postgresql_using="embedding::vector",
        existing_nullable=False,
    )
    op.alter_column(
        "job_embeddings",
        "embedding_dimensions",
        existing_type=sa.Integer(),
        server_default=None,
        existing_nullable=False,
    )
    op.drop_constraint("ck_job_embeddings_dimensions_384", "job_embeddings", type_="check")
    op.drop_constraint("uq_crawl_job_events_job_sequence", "crawl_job_events", type_="unique")
