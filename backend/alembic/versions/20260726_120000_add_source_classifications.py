"""add ordinary Source classifications

Revision ID: 20260726_120000
Revises: 20260723_120000
Create Date: 2026-07-26 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260726_120000"
down_revision = "20260723_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_classifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("classification_id", sa.String(length=255), nullable=False),
        sa.Column("native_id", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("is_top_level", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("query_metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_source_classification_source",
        ),
        sa.CheckConstraint("depth >= 0", name="ck_source_classification_depth"),
        sa.CheckConstraint(
            "classification_id LIKE source_site || ':%' "
            "AND length(classification_id) > length(source_site) + 1",
            name="ck_source_classification_identity",
        ),
        sa.CheckConstraint(
            "(depth = 0 AND is_top_level) OR (depth > 0 AND NOT is_top_level)",
            name="ck_source_classification_top_level",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["source_classifications.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_site",
            "classification_id",
            name="uq_source_classification_source_identity",
        ),
    )
    op.create_index(
        "ix_source_classification_active_roots",
        "source_classifications",
        ["source_site", "is_active", "is_top_level"],
    )
    op.create_index(
        op.f("ix_source_classifications_parent_id"),
        "source_classifications",
        ["parent_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_source_classifications_parent_id"),
        table_name="source_classifications",
    )
    op.drop_index(
        "ix_source_classification_active_roots",
        table_name="source_classifications",
    )
    op.drop_table("source_classifications")
