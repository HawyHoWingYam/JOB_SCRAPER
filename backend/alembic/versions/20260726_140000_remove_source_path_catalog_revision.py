"""remove Source Catalog revision from Job classification paths

Revision ID: 20260726_140000
Revises: 20260726_120000
Create Date: 2026-07-26 14:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260726_140000"
down_revision = "20260726_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_job_source_classification_path_catalog_source",
        "job_source_classification_paths",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_job_source_classification_paths_source_catalog_revision_id",
        table_name="job_source_classification_paths",
    )
    op.drop_column(
        "job_source_classification_paths",
        "source_catalog_revision_id",
    )


def downgrade() -> None:
    op.add_column(
        "job_source_classification_paths",
        sa.Column(
            "source_catalog_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_job_source_classification_paths_source_catalog_revision_id",
        "job_source_classification_paths",
        ["source_catalog_revision_id"],
    )
    op.create_foreign_key(
        "fk_job_source_classification_path_catalog_source",
        "job_source_classification_paths",
        "source_catalog_revisions",
        ["source_catalog_revision_id", "source_site"],
        ["id", "source_site"],
        ondelete="RESTRICT",
    )
