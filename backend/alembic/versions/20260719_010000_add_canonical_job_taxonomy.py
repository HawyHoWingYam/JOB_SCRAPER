"""add governed Canonical Job Taxonomy

Revision ID: 20260719_010000
Revises: 20260718_220000
Create Date: 2026-07-19 01:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260719_010000"
down_revision = "20260718_220000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_job_taxonomy_releases",
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("expected_domain_count", sa.Integer(), nullable=False),
        sa.Column("expected_category_count", sa.Integer(), nullable=False),
        sa.Column("expected_subcategory_count", sa.Integer(), nullable=False),
        sa.Column(
            "materialized_domain_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "materialized_category_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "materialized_subcategory_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="materializing",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_job_taxonomy_release_hash",
        ),
        sa.CheckConstraint(
            "expected_domain_count >= 0 AND expected_category_count >= 0 "
            "AND expected_subcategory_count >= 0",
            name="ck_canonical_job_taxonomy_release_expected_counts",
        ),
        sa.CheckConstraint(
            "materialized_domain_count >= 0 AND materialized_category_count >= 0 "
            "AND materialized_subcategory_count >= 0",
            name="ck_canonical_job_taxonomy_release_materialized_counts",
        ),
        sa.CheckConstraint(
            "status IN ('materializing', 'ready')",
            name="ck_canonical_job_taxonomy_release_status",
        ),
        sa.CheckConstraint(
            "(status = 'materializing' AND ready_at IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL "
            "AND expected_domain_count = materialized_domain_count "
            "AND expected_category_count = materialized_category_count "
            "AND expected_subcategory_count = materialized_subcategory_count)",
            name="ck_canonical_job_taxonomy_release_ready",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["governance_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint(
            "revision_id",
            "content_hash",
            name="uq_canonical_job_taxonomy_release_hash",
        ),
    )

    op.create_table(
        "canonical_job_taxonomy_active_revisions",
        sa.Column("singleton_key", sa.String(length=64), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "singleton_key = 'canonical-job-taxonomy'",
            name="ck_canonical_job_taxonomy_active_singleton",
        ),
        sa.CheckConstraint(
            "lock_version > 0",
            name="ck_canonical_job_taxonomy_active_version",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "content_hash"],
            [
                "canonical_job_taxonomy_releases.revision_id",
                "canonical_job_taxonomy_releases.content_hash",
            ],
            name="fk_canonical_job_taxonomy_active_release",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("singleton_key"),
        sa.UniqueConstraint(
            "revision_id",
            name="uq_canonical_job_taxonomy_active_revision",
        ),
    )

    op.create_table(
        "canonical_job_domains",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["canonical_job_taxonomy_releases.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_canonical_job_domain_code",
        ),
        sa.CheckConstraint(
            "length(trim(label)) > 0",
            name="ck_canonical_job_domain_label",
        ),
        sa.CheckConstraint(
            "source_order > 0",
            name="ck_canonical_job_domain_order",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "revision_id",
            name="uq_canonical_job_domain_id_revision",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "code",
            name="uq_canonical_job_domain_code",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "label",
            name="uq_canonical_job_domain_label",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "source_order",
            name="uq_canonical_job_domain_order",
        ),
    )
    op.create_index(
        "ix_canonical_job_domains_revision_id",
        "canonical_job_domains",
        ["revision_id"],
    )

    op.create_table(
        "canonical_job_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["domain_id", "revision_id"],
            ["canonical_job_domains.id", "canonical_job_domains.revision_id"],
            name="fk_canonical_job_category_domain_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_canonical_job_category_code",
        ),
        sa.CheckConstraint(
            "length(trim(label)) > 0",
            name="ck_canonical_job_category_label",
        ),
        sa.CheckConstraint(
            "source_order > 0",
            name="ck_canonical_job_category_order",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "revision_id",
            name="uq_canonical_job_category_id_revision",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "code",
            name="uq_canonical_job_category_code",
        ),
        sa.UniqueConstraint(
            "domain_id",
            "label",
            name="uq_canonical_job_category_label",
        ),
        sa.UniqueConstraint(
            "domain_id",
            "source_order",
            name="uq_canonical_job_category_order",
        ),
    )
    op.create_index(
        "ix_canonical_job_categories_revision_id",
        "canonical_job_categories",
        ["revision_id"],
    )
    op.create_index(
        "ix_canonical_job_categories_domain_id",
        "canonical_job_categories",
        ["domain_id"],
    )

    op.create_table(
        "canonical_job_subcategories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column(
            "is_assignable", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "revision_id"],
            [
                "canonical_job_categories.id",
                "canonical_job_categories.revision_id",
            ],
            name="fk_canonical_job_subcategory_category_revision",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_canonical_job_subcategory_code",
        ),
        sa.CheckConstraint(
            "length(trim(label)) > 0",
            name="ck_canonical_job_subcategory_label",
        ),
        sa.CheckConstraint(
            "source_order > 0",
            name="ck_canonical_job_subcategory_order",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "revision_id",
            name="uq_canonical_job_subcategory_id_revision",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "code",
            name="uq_canonical_job_subcategory_code",
        ),
        sa.UniqueConstraint(
            "category_id",
            "label",
            name="uq_canonical_job_subcategory_label",
        ),
        sa.UniqueConstraint(
            "category_id",
            "source_order",
            name="uq_canonical_job_subcategory_order",
        ),
    )
    op.create_index(
        "ix_canonical_job_subcategories_revision_id",
        "canonical_job_subcategories",
        ["revision_id"],
    )
    op.create_index(
        "ix_canonical_job_subcategories_category_id",
        "canonical_job_subcategories",
        ["category_id"],
    )
    op.create_index(
        "ix_canonical_job_subcategories_assignable",
        "canonical_job_subcategories",
        ["revision_id", "is_assignable"],
    )

    op.create_table(
        "canonical_job_taxonomy_mapping_revisions",
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("expected_coverage_count", sa.Integer(), nullable=False),
        sa.Column("expected_entry_count", sa.Integer(), nullable=False),
        sa.Column("expected_target_count", sa.Integer(), nullable=False),
        sa.Column(
            "materialized_coverage_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "materialized_entry_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "materialized_target_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="materializing",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_job_mapping_revision_hash",
        ),
        sa.CheckConstraint(
            "expected_coverage_count >= 0 AND expected_entry_count >= 0 "
            "AND expected_target_count >= 0",
            name="ck_canonical_job_mapping_revision_expected_counts",
        ),
        sa.CheckConstraint(
            "materialized_coverage_count >= 0 AND materialized_entry_count >= 0 "
            "AND materialized_target_count >= 0",
            name="ck_canonical_job_mapping_revision_materialized_counts",
        ),
        sa.CheckConstraint(
            "status IN ('materializing', 'ready')",
            name="ck_canonical_job_mapping_revision_status",
        ),
        sa.CheckConstraint(
            "(status = 'materializing' AND ready_at IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL "
            "AND expected_coverage_count = materialized_coverage_count "
            "AND expected_entry_count = materialized_entry_count "
            "AND expected_target_count = materialized_target_count)",
            name="ck_canonical_job_mapping_revision_ready",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["governance_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_revision_id"],
            ["canonical_job_taxonomy_releases.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("revision_id"),
        sa.UniqueConstraint(
            "revision_id",
            "taxonomy_revision_id",
            name="uq_canonical_job_mapping_revision_taxonomy",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "taxonomy_revision_id",
            "content_hash",
            name="uq_canonical_job_mapping_revision_identity",
        ),
    )

    op.create_table(
        "canonical_job_taxonomy_mapping_coverages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column(
            "source_catalog_revision_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("source_catalog_sequence", sa.Integer(), nullable=False),
        sa.Column("source_catalog_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("identity_set_hash", sa.String(length=64), nullable=False),
        sa.Column("identity_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_canonical_job_mapping_coverage_source",
        ),
        sa.CheckConstraint(
            "source_catalog_sequence > 0 AND identity_count >= 0",
            name="ck_canonical_job_mapping_coverage_counts",
        ),
        sa.CheckConstraint(
            "source_catalog_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND identity_set_hash ~ '^[0-9a-f]{64}$'",
            name="ck_canonical_job_mapping_coverage_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id"],
            ["canonical_job_taxonomy_mapping_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_catalog_revision_id", "source_site"],
            ["source_catalog_revisions.id", "source_catalog_revisions.source_site"],
            name="fk_canonical_job_mapping_coverage_catalog_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "mapping_revision_id",
            "source_site",
            name="uq_canonical_job_mapping_coverage_identity",
        ),
        sa.UniqueConstraint(
            "mapping_revision_id",
            "source_site",
            name="uq_canonical_job_mapping_coverage_source",
        ),
    )
    op.create_index(
        "ix_canonical_job_mapping_coverages_catalog_revision",
        "canonical_job_taxonomy_mapping_coverages",
        ["source_catalog_revision_id"],
    )

    op.create_table(
        "source_job_taxonomy_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coverage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("source_classification_id", sa.String(length=255), nullable=False),
        sa.Column("source_label", sa.String(length=255), nullable=False),
        sa.Column("disposition", sa.String(length=32), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("review_evidence", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "disposition IN ('deterministic', 'allowed_slice', 'excluded', 'unmapped')",
            name="ck_source_job_taxonomy_mapping_disposition",
        ),
        sa.CheckConstraint(
            "source_classification_id LIKE source_site || ':%' "
            "AND length(source_classification_id) > length(source_site) + 1",
            name="ck_source_job_taxonomy_mapping_identity",
        ),
        sa.CheckConstraint(
            "source_order > 0 AND length(trim(source_label)) > 0",
            name="ck_source_job_taxonomy_mapping_content",
        ),
        sa.ForeignKeyConstraint(
            ["coverage_id", "mapping_revision_id", "source_site"],
            [
                "canonical_job_taxonomy_mapping_coverages.id",
                "canonical_job_taxonomy_mapping_coverages.mapping_revision_id",
                "canonical_job_taxonomy_mapping_coverages.source_site",
            ],
            name="fk_source_job_taxonomy_mapping_coverage",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "mapping_revision_id",
            name="uq_source_job_taxonomy_mapping_id_revision",
        ),
        sa.UniqueConstraint(
            "mapping_revision_id",
            "source_site",
            "source_classification_id",
            name="uq_source_job_taxonomy_mapping_identity",
        ),
        sa.UniqueConstraint(
            "mapping_revision_id",
            "source_order",
            name="uq_source_job_taxonomy_mapping_order",
        ),
    )
    op.create_index(
        "ix_source_job_taxonomy_mapping_lookup",
        "source_job_taxonomy_mappings",
        ["mapping_revision_id", "source_site", "source_classification_id"],
    )

    op.create_table(
        "source_job_taxonomy_mapping_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("subcategory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "role IN ('deterministic', 'allowed')",
            name="ck_source_job_taxonomy_mapping_target_role",
        ),
        sa.CheckConstraint(
            "source_order > 0",
            name="ck_source_job_taxonomy_mapping_target_order",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_id", "mapping_revision_id"],
            [
                "source_job_taxonomy_mappings.id",
                "source_job_taxonomy_mappings.mapping_revision_id",
            ],
            name="fk_source_job_taxonomy_mapping_target_mapping",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subcategory_id", "taxonomy_revision_id"],
            [
                "canonical_job_subcategories.id",
                "canonical_job_subcategories.revision_id",
            ],
            name="fk_source_job_taxonomy_mapping_target_subcategory",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mapping_id",
            "subcategory_id",
            name="uq_source_job_taxonomy_mapping_target",
        ),
        sa.UniqueConstraint(
            "mapping_id",
            "source_order",
            name="uq_source_job_taxonomy_mapping_target_order",
        ),
    )
    op.create_index(
        "ix_source_job_taxonomy_mapping_targets_subcategory",
        "source_job_taxonomy_mapping_targets",
        ["taxonomy_revision_id", "subcategory_id"],
    )

    op.create_table(
        "canonical_job_taxonomy_active_mapping_revisions",
        sa.Column("singleton_key", sa.String(length=64), nullable=False),
        sa.Column("mapping_revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "singleton_key = 'canonical-job-taxonomy-mapping'",
            name="ck_canonical_job_mapping_active_singleton",
        ),
        sa.CheckConstraint(
            "lock_version > 0",
            name="ck_canonical_job_mapping_active_version",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id", "taxonomy_revision_id", "content_hash"],
            [
                "canonical_job_taxonomy_mapping_revisions.revision_id",
                "canonical_job_taxonomy_mapping_revisions.taxonomy_revision_id",
                "canonical_job_taxonomy_mapping_revisions.content_hash",
            ],
            name="fk_canonical_job_mapping_active_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("singleton_key"),
        sa.UniqueConstraint(
            "mapping_revision_id",
            name="uq_canonical_job_mapping_active_revision",
        ),
    )

    op.create_table(
        "job_taxonomy_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("subcategory_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("source_evidence_refs", sa.JSON(), nullable=False),
        sa.Column("mapping_ids", sa.JSON(), nullable=False),
        sa.Column("model_provider", sa.String(length=100), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("breadcrumb", sa.JSON(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "method IN ('reviewed_mapping', 'constrained_ai', 'operator')",
            name="ck_job_taxonomy_assignment_method",
        ),
        sa.CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$'",
            name="ck_job_taxonomy_assignment_evidence_hash",
        ),
        sa.CheckConstraint(
            "lock_version > 0",
            name="ck_job_taxonomy_assignment_version",
        ),
        sa.CheckConstraint(
            "(is_current AND superseded_at IS NULL) OR "
            "(NOT is_current AND superseded_at IS NOT NULL)",
            name="ck_job_taxonomy_assignment_current",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["subcategory_id", "taxonomy_revision_id"],
            [
                "canonical_job_subcategories.id",
                "canonical_job_subcategories.revision_id",
            ],
            name="fk_job_taxonomy_assignment_subcategory",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id", "taxonomy_revision_id"],
            [
                "canonical_job_taxonomy_mapping_revisions.revision_id",
                "canonical_job_taxonomy_mapping_revisions.taxonomy_revision_id",
            ],
            name="fk_job_taxonomy_assignment_mapping_taxonomy",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_taxonomy_assignments_job_id",
        "job_taxonomy_assignments",
        ["job_id"],
    )
    op.create_index(
        "ix_job_taxonomy_assignments_subcategory",
        "job_taxonomy_assignments",
        ["taxonomy_revision_id", "subcategory_id"],
    )
    op.create_index(
        "ux_job_taxonomy_assignment_current",
        "job_taxonomy_assignments",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "job_taxonomy_review_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("mapping_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="active"
        ),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("decision_audit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'assigned', 'insufficient_evidence', 'superseded')",
            name="ck_job_taxonomy_review_status",
        ),
        sa.CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$' AND lock_version > 0",
            name="ck_job_taxonomy_review_evidence_version",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND resolved_at IS NULL) OR "
            "(status <> 'active' AND resolved_at IS NOT NULL)",
            name="ck_job_taxonomy_review_resolution",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["taxonomy_revision_id"],
            ["canonical_job_taxonomy_releases.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_revision_id"],
            ["canonical_job_taxonomy_mapping_revisions.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_audit_id"],
            ["governance_audit_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["job_taxonomy_assignments.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_job_taxonomy_review_items_job_id",
        "job_taxonomy_review_items",
        ["job_id"],
    )
    op.create_index(
        "ix_job_taxonomy_review_items_status_created",
        "job_taxonomy_review_items",
        ["status", "created_at", "id"],
    )
    op.create_index(
        "ux_job_taxonomy_review_active",
        "job_taxonomy_review_items",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    _create_release_guards()
    _create_immutable_content_guards()
    _create_active_pointer_guards()


def _create_release_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_canonical_job_taxonomy_release_ready()
        RETURNS trigger AS $$
        DECLARE
            actual_domain_count integer;
            actual_category_count integer;
            actual_subcategory_count integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ready canonical taxonomy releases are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status = 'ready' THEN
                RAISE EXCEPTION 'ready canonical taxonomy releases are immutable';
            END IF;
            IF NEW.status = 'ready' THEN
                SELECT count(*) INTO actual_domain_count
                FROM canonical_job_domains
                WHERE revision_id = NEW.revision_id;
                SELECT count(*) INTO actual_category_count
                FROM canonical_job_categories
                WHERE revision_id = NEW.revision_id;
                SELECT count(*) INTO actual_subcategory_count
                FROM canonical_job_subcategories
                WHERE revision_id = NEW.revision_id;
                IF actual_domain_count <> NEW.expected_domain_count
                   OR actual_domain_count <> NEW.materialized_domain_count
                   OR actual_category_count <> NEW.expected_category_count
                   OR actual_category_count <> NEW.materialized_category_count
                   OR actual_subcategory_count <> NEW.expected_subcategory_count
                   OR actual_subcategory_count <> NEW.materialized_subcategory_count
                THEN
                    RAISE EXCEPTION 'ready canonical taxonomy release counts do not match materialized nodes';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_canonical_job_taxonomy_release_ready_guard
        BEFORE INSERT OR UPDATE OR DELETE ON canonical_job_taxonomy_releases
        FOR EACH ROW EXECUTE FUNCTION guard_canonical_job_taxonomy_release_ready()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_canonical_job_mapping_revision_ready()
        RETURNS trigger AS $$
        DECLARE
            actual_coverage_count integer;
            actual_entry_count integer;
            actual_target_count integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ready canonical mapping revisions are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status = 'ready' THEN
                RAISE EXCEPTION 'ready canonical mapping revisions are immutable';
            END IF;
            IF NEW.status = 'ready' THEN
                SELECT count(*) INTO actual_coverage_count
                FROM canonical_job_taxonomy_mapping_coverages
                WHERE mapping_revision_id = NEW.revision_id;
                SELECT count(*) INTO actual_entry_count
                FROM source_job_taxonomy_mappings
                WHERE mapping_revision_id = NEW.revision_id;
                SELECT count(*) INTO actual_target_count
                FROM source_job_taxonomy_mapping_targets
                WHERE mapping_revision_id = NEW.revision_id;
                IF actual_coverage_count <> NEW.expected_coverage_count
                   OR actual_coverage_count <> NEW.materialized_coverage_count
                   OR actual_entry_count <> NEW.expected_entry_count
                   OR actual_entry_count <> NEW.materialized_entry_count
                   OR actual_target_count <> NEW.expected_target_count
                   OR actual_target_count <> NEW.materialized_target_count
                THEN
                    RAISE EXCEPTION 'ready canonical mapping revision counts do not match materialized rows';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_canonical_job_mapping_revision_ready_guard
        BEFORE INSERT OR UPDATE OR DELETE ON canonical_job_taxonomy_mapping_revisions
        FOR EACH ROW EXECUTE FUNCTION guard_canonical_job_mapping_revision_ready()
        """
    )


def _create_immutable_content_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_canonical_job_taxonomy_node_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF EXISTS (
                    SELECT 1 FROM canonical_job_taxonomy_releases release
                    WHERE release.revision_id = NEW.revision_id
                      AND release.status = 'materializing'
                ) THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'canonical taxonomy nodes may only be inserted while materializing';
            END IF;
            RAISE EXCEPTION 'canonical taxonomy nodes are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in (
        "canonical_job_domains",
        "canonical_job_categories",
        "canonical_job_subcategories",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_canonical_job_taxonomy_nodes_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_canonical_job_taxonomy_node_mutation()
            """
        )

    op.execute(
        """
        CREATE FUNCTION reject_canonical_job_mapping_content_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF EXISTS (
                    SELECT 1 FROM canonical_job_taxonomy_mapping_revisions mapping
                    WHERE mapping.revision_id = NEW.mapping_revision_id
                      AND mapping.status = 'materializing'
                ) THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'canonical mapping rows may only be inserted while materializing';
            END IF;
            RAISE EXCEPTION 'canonical mapping content is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in (
        "canonical_job_taxonomy_mapping_coverages",
        "source_job_taxonomy_mappings",
        "source_job_taxonomy_mapping_targets",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_canonical_job_mapping_content_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION reject_canonical_job_mapping_content_mutation()
            """
        )


def _create_active_pointer_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION require_ready_canonical_job_taxonomy_release()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'canonical taxonomy active pointer cannot be deleted';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM canonical_job_taxonomy_releases release
                WHERE release.revision_id = NEW.revision_id
                  AND release.content_hash = NEW.content_hash
                  AND release.status = 'ready'
                  AND release.expected_domain_count = release.materialized_domain_count
                  AND release.expected_category_count = release.materialized_category_count
                  AND release.expected_subcategory_count = release.materialized_subcategory_count
            ) THEN
                RAISE EXCEPTION 'canonical taxonomy active pointer requires a ready release';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_canonical_job_taxonomy_active_ready
        BEFORE INSERT OR UPDATE OR DELETE ON canonical_job_taxonomy_active_revisions
        FOR EACH ROW EXECUTE FUNCTION require_ready_canonical_job_taxonomy_release()
        """
    )
    op.execute(
        """
        CREATE FUNCTION require_ready_canonical_job_mapping_revision()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'canonical mapping active pointer cannot be deleted';
            END IF;
            IF NOT EXISTS (
                SELECT 1 FROM canonical_job_taxonomy_mapping_revisions mapping
                JOIN canonical_job_taxonomy_active_revisions taxonomy
                  ON taxonomy.revision_id = mapping.taxonomy_revision_id
                WHERE mapping.revision_id = NEW.mapping_revision_id
                  AND mapping.taxonomy_revision_id = NEW.taxonomy_revision_id
                  AND mapping.content_hash = NEW.content_hash
                  AND mapping.status = 'ready'
                  AND mapping.expected_coverage_count = mapping.materialized_coverage_count
                  AND mapping.expected_entry_count = mapping.materialized_entry_count
                  AND mapping.expected_target_count = mapping.materialized_target_count
            ) THEN
                RAISE EXCEPTION 'canonical mapping active pointer requires a ready current-taxonomy revision';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_canonical_job_mapping_active_ready
        BEFORE INSERT OR UPDATE OR DELETE ON canonical_job_taxonomy_active_mapping_revisions
        FOR EACH ROW EXECUTE FUNCTION require_ready_canonical_job_mapping_revision()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_canonical_job_mapping_active_ready "
        "ON canonical_job_taxonomy_active_mapping_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS require_ready_canonical_job_mapping_revision()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_canonical_job_taxonomy_active_ready "
        "ON canonical_job_taxonomy_active_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS require_ready_canonical_job_taxonomy_release()")

    for table_name in (
        "source_job_taxonomy_mapping_targets",
        "source_job_taxonomy_mappings",
        "canonical_job_taxonomy_mapping_coverages",
    ):
        op.execute(
            "DROP TRIGGER IF EXISTS trg_canonical_job_mapping_content_immutable "
            f"ON {table_name}"
        )
    op.execute(
        "DROP FUNCTION IF EXISTS reject_canonical_job_mapping_content_mutation()"
    )

    for table_name in (
        "canonical_job_subcategories",
        "canonical_job_categories",
        "canonical_job_domains",
    ):
        op.execute(
            "DROP TRIGGER IF EXISTS trg_canonical_job_taxonomy_nodes_immutable "
            f"ON {table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS reject_canonical_job_taxonomy_node_mutation()")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_canonical_job_mapping_revision_ready_guard "
        "ON canonical_job_taxonomy_mapping_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_canonical_job_mapping_revision_ready()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_canonical_job_taxonomy_release_ready_guard "
        "ON canonical_job_taxonomy_releases"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_canonical_job_taxonomy_release_ready()")

    op.drop_index(
        "ux_job_taxonomy_review_active", table_name="job_taxonomy_review_items"
    )
    op.drop_index(
        "ix_job_taxonomy_review_items_status_created",
        table_name="job_taxonomy_review_items",
    )
    op.drop_index(
        "ix_job_taxonomy_review_items_job_id", table_name="job_taxonomy_review_items"
    )
    op.drop_table("job_taxonomy_review_items")

    op.drop_index(
        "ux_job_taxonomy_assignment_current", table_name="job_taxonomy_assignments"
    )
    op.drop_index(
        "ix_job_taxonomy_assignments_subcategory", table_name="job_taxonomy_assignments"
    )
    op.drop_index(
        "ix_job_taxonomy_assignments_job_id", table_name="job_taxonomy_assignments"
    )
    op.drop_table("job_taxonomy_assignments")

    op.drop_table("canonical_job_taxonomy_active_mapping_revisions")

    op.drop_index(
        "ix_source_job_taxonomy_mapping_targets_subcategory",
        table_name="source_job_taxonomy_mapping_targets",
    )
    op.drop_table("source_job_taxonomy_mapping_targets")

    op.drop_index(
        "ix_source_job_taxonomy_mapping_lookup",
        table_name="source_job_taxonomy_mappings",
    )
    op.drop_table("source_job_taxonomy_mappings")

    op.drop_index(
        "ix_canonical_job_mapping_coverages_catalog_revision",
        table_name="canonical_job_taxonomy_mapping_coverages",
    )
    op.drop_table("canonical_job_taxonomy_mapping_coverages")
    op.drop_table("canonical_job_taxonomy_mapping_revisions")

    op.drop_index(
        "ix_canonical_job_subcategories_assignable",
        table_name="canonical_job_subcategories",
    )
    op.drop_index(
        "ix_canonical_job_subcategories_category_id",
        table_name="canonical_job_subcategories",
    )
    op.drop_index(
        "ix_canonical_job_subcategories_revision_id",
        table_name="canonical_job_subcategories",
    )
    op.drop_table("canonical_job_subcategories")

    op.drop_index(
        "ix_canonical_job_categories_domain_id",
        table_name="canonical_job_categories",
    )
    op.drop_index(
        "ix_canonical_job_categories_revision_id",
        table_name="canonical_job_categories",
    )
    op.drop_table("canonical_job_categories")

    op.drop_index(
        "ix_canonical_job_domains_revision_id",
        table_name="canonical_job_domains",
    )
    op.drop_table("canonical_job_domains")
    op.drop_table("canonical_job_taxonomy_active_revisions")
    op.drop_table("canonical_job_taxonomy_releases")
