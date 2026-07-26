"""remove Source Catalog revision from crawl dispatch plans

Revision ID: 20260726_160000
Revises: 20260726_140000
Create Date: 2026-07-26 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260726_160000"
down_revision = "20260726_140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_crawl_dispatch_plans_catalog_revision_source",
        "crawl_dispatch_plans",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_crawl_dispatch_plans_catalog_revision_id",
        table_name="crawl_dispatch_plans",
    )
    op.drop_column("crawl_dispatch_plans", "catalog_revision_id")


def downgrade() -> None:
    op.add_column(
        "crawl_dispatch_plans",
        sa.Column(
            "catalog_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_crawl_dispatch_plans_catalog_revision_id",
        "crawl_dispatch_plans",
        ["catalog_revision_id"],
    )
    op.create_foreign_key(
        "fk_crawl_dispatch_plans_catalog_revision_source",
        "crawl_dispatch_plans",
        "source_catalog_revisions",
        ["catalog_revision_id", "source_site"],
        ["id", "source_site"],
        ondelete="RESTRICT",
    )
