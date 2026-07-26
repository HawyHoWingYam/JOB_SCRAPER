"""drop Source Catalog governance and revision persistence

Revision ID: 20260726_180000
Revises: 20260726_160000
Create Date: 2026-07-26 18:00:00.000000
"""

from alembic import op


revision = "20260726_180000"
down_revision = "20260726_160000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "fk_canonical_job_mapping_coverage_catalog_source",
        "canonical_job_taxonomy_mapping_coverages",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_canonical_job_mapping_coverage_counts",
        "canonical_job_taxonomy_mapping_coverages",
        type_="check",
    )
    op.drop_constraint(
        "ck_canonical_job_mapping_coverage_hashes",
        "canonical_job_taxonomy_mapping_coverages",
        type_="check",
    )
    op.drop_index(
        "ix_canonical_job_mapping_coverages_catalog_revision",
        table_name="canonical_job_taxonomy_mapping_coverages",
    )
    op.drop_column(
        "canonical_job_taxonomy_mapping_coverages",
        "source_catalog_fingerprint",
    )
    op.drop_column(
        "canonical_job_taxonomy_mapping_coverages",
        "source_catalog_sequence",
    )
    op.drop_column(
        "canonical_job_taxonomy_mapping_coverages",
        "source_catalog_revision_id",
    )
    op.create_check_constraint(
        "ck_canonical_job_mapping_coverage_counts",
        "canonical_job_taxonomy_mapping_coverages",
        "identity_count >= 0",
    )
    op.create_check_constraint(
        "ck_canonical_job_mapping_coverage_hashes",
        "canonical_job_taxonomy_mapping_coverages",
        "identity_set_hash ~ '^[0-9a-f]{64}$'",
    )

    op.drop_table("source_catalog_publications")
    op.drop_table("source_catalog_change_reviews")
    op.drop_table("source_catalog_active_revisions")
    op.drop_table("source_catalog_revisions")
    op.drop_table("source_catalog_validation_runs")
    op.drop_table("source_catalog_candidates")

    op.execute("DROP FUNCTION IF EXISTS reject_source_catalog_revision_mutation()")
    op.execute(
        "DROP FUNCTION IF EXISTS "
        "reject_source_catalog_candidate_payload_mutation()"
    )


def downgrade() -> None:
    raise RuntimeError(
        "Source Catalog governance removal is an intentional sandbox cutover"
    )
