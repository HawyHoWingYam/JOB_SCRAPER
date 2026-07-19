"""add governed Skill taxonomy and Candidate lifecycle

Revision ID: 20260719_160000
Revises: 20260719_120000
Create Date: 2026-07-19 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260719_160000"
down_revision = "20260719_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "skill_taxonomy_releases",
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("taxonomy_hash", sa.String(length=64), nullable=False),
        sa.Column("rules_hash", sa.String(length=64), nullable=False),
        sa.Column("backfill_hash", sa.String(length=64), nullable=False),
        sa.Column("rules_document", sa.JSON(), nullable=False),
        sa.Column("backfill_document", sa.JSON(), nullable=False),
        sa.Column("expected_category_count", sa.Integer(), nullable=False),
        sa.Column("expected_technology_count", sa.Integer(), nullable=False),
        sa.Column("expected_skill_count", sa.Integer(), nullable=False),
        sa.Column("expected_alias_count", sa.Integer(), nullable=False),
        sa.Column(
            "materialized_category_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "materialized_technology_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "materialized_skill_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "materialized_alias_count",
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
            "content_hash ~ '^[0-9a-f]{64}$' AND "
            "taxonomy_hash ~ '^[0-9a-f]{64}$' AND "
            "rules_hash ~ '^[0-9a-f]{64}$' AND "
            "backfill_hash ~ '^[0-9a-f]{64}$'",
            name="ck_skill_taxonomy_release_hashes",
        ),
        sa.CheckConstraint(
            "expected_category_count >= 0 AND expected_technology_count >= 0 "
            "AND expected_skill_count >= 0 AND expected_alias_count >= 0",
            name="ck_skill_taxonomy_release_expected_counts",
        ),
        sa.CheckConstraint(
            "materialized_category_count >= 0 "
            "AND materialized_technology_count >= 0 "
            "AND materialized_skill_count >= 0 "
            "AND materialized_alias_count >= 0",
            name="ck_skill_taxonomy_release_materialized_counts",
        ),
        sa.CheckConstraint(
            "status IN ('materializing', 'ready')",
            name="ck_skill_taxonomy_release_status",
        ),
        sa.CheckConstraint(
            "(status = 'materializing' AND ready_at IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL "
            "AND expected_category_count = materialized_category_count "
            "AND expected_technology_count = materialized_technology_count "
            "AND expected_skill_count = materialized_skill_count "
            "AND expected_alias_count = materialized_alias_count)",
            name="ck_skill_taxonomy_release_ready",
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
            name="uq_skill_taxonomy_release_hash",
        ),
    )

    op.create_table(
        "skill_taxonomy_active_revisions",
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
            "singleton_key = 'skill-taxonomy'",
            name="ck_skill_taxonomy_active_singleton",
        ),
        sa.CheckConstraint(
            "lock_version > 0",
            name="ck_skill_taxonomy_active_version",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "content_hash"],
            [
                "skill_taxonomy_releases.revision_id",
                "skill_taxonomy_releases.content_hash",
            ],
            name="fk_skill_taxonomy_active_release",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("singleton_key"),
        sa.UniqueConstraint(
            "revision_id",
            name="uq_skill_taxonomy_active_revision",
        ),
    )

    op.create_table(
        "governed_skill_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_governed_skill_category_code",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0 AND source_order > 0",
            name="ck_governed_skill_category_content",
        ),
        sa.CheckConstraint(
            "(is_active AND retired_at IS NULL) OR "
            "(NOT is_active AND retired_at IS NOT NULL)",
            name="ck_governed_skill_category_retirement",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["skill_taxonomy_releases.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "revision_id",
            name="uq_governed_skill_category_id_revision",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "code",
            name="uq_governed_skill_category_code",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "name",
            name="uq_governed_skill_category_name",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "source_order",
            name="uq_governed_skill_category_order",
        ),
    )
    op.create_index(
        "ix_governed_skill_categories_revision_id",
        "governed_skill_categories",
        ["revision_id"],
    )

    op.create_table(
        "governed_skill_technologies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_governed_skill_technology_code",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0 AND source_order > 0",
            name="ck_governed_skill_technology_content",
        ),
        sa.CheckConstraint(
            "(is_active AND retired_at IS NULL) OR "
            "(NOT is_active AND retired_at IS NOT NULL)",
            name="ck_governed_skill_technology_retirement",
        ),
        sa.ForeignKeyConstraint(
            ["category_id", "revision_id"],
            [
                "governed_skill_categories.id",
                "governed_skill_categories.revision_id",
            ],
            name="fk_governed_skill_technology_category",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "revision_id",
            name="uq_governed_skill_technology_id_revision",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "code",
            name="uq_governed_skill_technology_code",
        ),
        sa.UniqueConstraint(
            "category_id",
            "name",
            name="uq_governed_skill_technology_name",
        ),
        sa.UniqueConstraint(
            "category_id",
            "source_order",
            name="uq_governed_skill_technology_order",
        ),
    )
    op.create_index(
        "ix_governed_skill_technologies_revision_id",
        "governed_skill_technologies",
        ["revision_id"],
    )
    op.create_index(
        "ix_governed_skill_technologies_category_id",
        "governed_skill_technologies",
        ["category_id"],
    )

    op.create_table(
        "governed_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("technology_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column(
            "origin", sa.String(length=32), nullable=False, server_default="seed"
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_by_audit_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "code ~ '^[a-z0-9]+([._-][a-z0-9]+)*$'",
            name="ck_governed_skill_code",
        ),
        sa.CheckConstraint(
            "length(trim(name)) > 0 AND source_order > 0",
            name="ck_governed_skill_content",
        ),
        sa.CheckConstraint(
            "origin IN ('seed', 'operator')",
            name="ck_governed_skill_origin",
        ),
        sa.CheckConstraint(
            "(is_active AND retired_at IS NULL) OR "
            "(NOT is_active AND retired_at IS NOT NULL)",
            name="ck_governed_skill_retirement",
        ),
        sa.ForeignKeyConstraint(
            ["technology_id", "revision_id"],
            [
                "governed_skill_technologies.id",
                "governed_skill_technologies.revision_id",
            ],
            name="fk_governed_skill_technology",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_audit_id"],
            ["governance_audit_events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "revision_id",
            name="uq_governed_skill_id_revision",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "code",
            name="uq_governed_skill_code",
        ),
        sa.UniqueConstraint(
            "technology_id",
            "name",
            name="uq_governed_skill_name",
        ),
        sa.UniqueConstraint(
            "technology_id",
            "source_order",
            name="uq_governed_skill_order",
        ),
    )
    op.create_index(
        "ix_governed_skills_revision_id",
        "governed_skills",
        ["revision_id"],
    )
    op.create_index(
        "ix_governed_skills_technology_id",
        "governed_skills",
        ["technology_id"],
    )
    op.create_index(
        "ix_governed_skills_active",
        "governed_skills",
        ["revision_id", "is_active", "code"],
    )

    op.create_table(
        "governed_skill_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_alias", sa.String(length=500), nullable=False),
        sa.Column("normalized_key", sa.String(length=500), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_by_audit_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "source IN ('canonical_name', 'taxonomy_alias', 'curation_alias', 'operator')",
            name="ck_governed_skill_alias_source",
        ),
        sa.CheckConstraint(
            "length(trim(raw_alias)) > 0 AND length(trim(normalized_key)) > 0 "
            "AND source_order > 0",
            name="ck_governed_skill_alias_content",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_audit_id"],
            ["governance_audit_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "taxonomy_revision_id"],
            ["governed_skills.id", "governed_skills.revision_id"],
            name="fk_governed_skill_alias_skill",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "taxonomy_revision_id",
            "normalized_key",
            name="uq_governed_skill_alias_key",
        ),
        sa.UniqueConstraint(
            "skill_id",
            "source_order",
            name="uq_governed_skill_alias_order",
        ),
    )
    op.create_index(
        "ix_governed_skill_aliases_taxonomy_revision_id",
        "governed_skill_aliases",
        ["taxonomy_revision_id"],
    )
    op.create_index(
        "ix_governed_skill_aliases_skill_id",
        "governed_skill_aliases",
        ["skill_id"],
    )
    op.create_index(
        "ix_governed_skill_alias_lookup",
        "governed_skill_aliases",
        ["taxonomy_revision_id", "normalized_key"],
    )

    op.create_table(
        "skill_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("normalized_key", sa.String(length=500), nullable=False),
        sa.Column("canonical_raw_name", sa.String(length=500), nullable=False),
        sa.Column(
            "raw_variants",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("suggested_category_code", sa.String(length=255), nullable=True),
        sa.Column("suggested_technology_code", sa.String(length=255), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "distinct_job_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "evidence_summary",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "recommendations",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("decision_audit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generic_tag", sa.String(length=500), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
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
            "status IN ('pending', 'resolved_merged', 'resolved_created', "
            "'resolved_generic', 'rejected', 'superseded')",
            name="ck_skill_candidate_status",
        ),
        sa.CheckConstraint(
            "occurrence_count >= 0 AND distinct_job_count >= 0 AND lock_version > 0",
            name="ck_skill_candidate_metrics_version",
        ),
        sa.CheckConstraint(
            "length(trim(normalized_key)) > 0 AND length(trim(canonical_raw_name)) > 0",
            name="ck_skill_candidate_identity",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL "
            "AND resolved_skill_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(status IN ('resolved_merged', 'resolved_created') "
            "AND resolved_at IS NOT NULL AND resolved_skill_id IS NOT NULL "
            "AND generic_tag IS NULL AND rejection_reason IS NULL) OR "
            "(status = 'resolved_generic' AND resolved_at IS NOT NULL "
            "AND resolved_skill_id IS NULL AND generic_tag IS NOT NULL "
            "AND length(trim(generic_tag)) > 0 AND rejection_reason IS NULL) OR "
            "(status = 'rejected' AND resolved_at IS NOT NULL "
            "AND resolved_skill_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NOT NULL "
            "AND length(trim(rejection_reason)) > 0) OR "
            "(status = 'superseded' AND resolved_at IS NOT NULL "
            "AND resolved_skill_id IS NULL AND generic_tag IS NULL)",
            name="ck_skill_candidate_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_revision_id"],
            ["skill_taxonomy_releases.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_skill_id", "taxonomy_revision_id"],
            ["governed_skills.id", "governed_skills.revision_id"],
            name="fk_skill_candidate_resolved_skill",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_audit_id"],
            ["governance_audit_events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "taxonomy_revision_id",
            name="uq_skill_candidate_id_revision",
        ),
        sa.UniqueConstraint(
            "taxonomy_revision_id",
            "normalized_key",
            name="uq_skill_candidate_key_revision",
        ),
    )
    op.create_index(
        "ix_skill_candidates_taxonomy_revision_id",
        "skill_candidates",
        ["taxonomy_revision_id"],
    )
    op.create_index(
        "ix_skill_candidates_queue",
        "skill_candidates",
        ["status", "last_seen_at", "id"],
    )

    op.create_table(
        "governed_job_skill_mentions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("raw_name", sa.String(length=500), nullable=False),
        sa.Column("normalized_key", sa.String(length=500), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("origin_candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("generic_tag", sa.String(length=500), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.String(length=64),
            nullable=False,
            server_default="ai-extraction",
        ),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "provenance",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
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
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "resolution IN ('match_existing', 'review_candidate', 'generic_tag', 'rejected')",
            name="ck_governed_job_skill_mention_resolution",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_governed_job_skill_mention_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND superseded_at IS NULL) OR "
            "(status = 'superseded' AND superseded_at IS NOT NULL)",
            name="ck_governed_job_skill_mention_superseded",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_governed_job_skill_mention_confidence",
        ),
        sa.CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$' AND lock_version > 0 "
            "AND length(trim(raw_name)) > 0 AND length(trim(normalized_key)) > 0",
            name="ck_governed_job_skill_mention_content",
        ),
        sa.CheckConstraint(
            "(resolution = 'match_existing' AND skill_id IS NOT NULL "
            "AND candidate_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(resolution = 'review_candidate' AND skill_id IS NULL "
            "AND candidate_id IS NOT NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NULL) OR "
            "(resolution = 'generic_tag' AND skill_id IS NULL "
            "AND candidate_id IS NULL AND generic_tag IS NOT NULL "
            "AND length(trim(generic_tag)) > 0 AND rejection_reason IS NULL) OR "
            "(resolution = 'rejected' AND skill_id IS NULL "
            "AND candidate_id IS NULL AND generic_tag IS NULL "
            "AND rejection_reason IS NOT NULL "
            "AND length(trim(rejection_reason)) > 0)",
            name="ck_governed_job_skill_mention_target",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_revision_id"],
            ["skill_taxonomy_releases.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "taxonomy_revision_id"],
            ["governed_skills.id", "governed_skills.revision_id"],
            name="fk_governed_job_skill_mention_skill",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id", "taxonomy_revision_id"],
            ["skill_candidates.id", "skill_candidates.taxonomy_revision_id"],
            name="fk_governed_job_skill_mention_candidate",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["origin_candidate_id", "taxonomy_revision_id"],
            ["skill_candidates.id", "skill_candidates.taxonomy_revision_id"],
            name="fk_governed_job_skill_mention_origin_candidate",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_governed_job_skill_mentions_job_id",
        "governed_job_skill_mentions",
        ["job_id"],
    )
    op.create_index(
        "ix_governed_job_skill_mentions_taxonomy_revision_id",
        "governed_job_skill_mentions",
        ["taxonomy_revision_id"],
    )
    op.create_index(
        "ux_governed_job_skill_mention_active_key",
        "governed_job_skill_mentions",
        ["job_id", "taxonomy_revision_id", "normalized_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ix_governed_job_skill_mentions_candidate",
        "governed_job_skill_mentions",
        ["candidate_id", "resolution", "job_id"],
    )
    op.create_index(
        "ix_governed_job_skill_mentions_skill",
        "governed_job_skill_mentions",
        ["taxonomy_revision_id", "skill_id", "job_id"],
    )

    op.create_table(
        "governed_job_skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "provenance",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("mention_count", sa.Integer(), nullable=False, server_default="1"),
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
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_governed_job_skill_confidence",
        ),
        sa.CheckConstraint(
            "mention_count > 0",
            name="ck_governed_job_skill_mention_count",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_revision_id"],
            ["skill_taxonomy_releases.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["skill_id", "taxonomy_revision_id"],
            ["governed_skills.id", "governed_skills.revision_id"],
            name="fk_governed_job_skill_skill",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "taxonomy_revision_id",
            "skill_id",
            name="uq_governed_job_skill_projection",
        ),
    )
    op.create_index(
        "ix_governed_job_skills_job_id",
        "governed_job_skills",
        ["job_id"],
    )
    op.create_index(
        "ix_governed_job_skills_taxonomy_revision_id",
        "governed_job_skills",
        ["taxonomy_revision_id"],
    )
    op.create_index(
        "ix_governed_job_skills_skill_id",
        "governed_job_skills",
        ["skill_id"],
    )
    op.create_index(
        "ix_governed_job_skills_filter",
        "governed_job_skills",
        ["taxonomy_revision_id", "skill_id", "job_id"],
    )

    _create_release_guards()
    _create_content_guards()
    _create_active_pointer_guards()
    _create_decision_audit_guards()


def _create_release_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_skill_taxonomy_release_ready()
        RETURNS trigger AS $$
        DECLARE
            actual_categories integer;
            actual_technologies integer;
            actual_skills integer;
            actual_aliases integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ready Skill taxonomy releases are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status = 'ready' THEN
                RAISE EXCEPTION 'ready Skill taxonomy releases are immutable';
            END IF;
            IF NEW.status = 'ready' THEN
                SELECT count(*) INTO actual_categories
                FROM governed_skill_categories WHERE revision_id = NEW.revision_id;
                SELECT count(*) INTO actual_technologies
                FROM governed_skill_technologies WHERE revision_id = NEW.revision_id;
                SELECT count(*) INTO actual_skills
                FROM governed_skills
                WHERE revision_id = NEW.revision_id AND origin = 'seed';
                SELECT count(*) INTO actual_aliases
                FROM governed_skill_aliases
                WHERE taxonomy_revision_id = NEW.revision_id;
                IF actual_categories <> NEW.expected_category_count
                   OR actual_categories <> NEW.materialized_category_count
                   OR actual_technologies <> NEW.expected_technology_count
                   OR actual_technologies <> NEW.materialized_technology_count
                   OR actual_skills <> NEW.expected_skill_count
                   OR actual_skills <> NEW.materialized_skill_count
                   OR actual_aliases <> NEW.expected_alias_count
                   OR actual_aliases <> NEW.materialized_alias_count
                THEN
                    RAISE EXCEPTION 'ready Skill taxonomy release counts do not match content';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_skill_taxonomy_release_ready_guard
        BEFORE INSERT OR UPDATE OR DELETE ON skill_taxonomy_releases
        FOR EACH ROW EXECUTE FUNCTION guard_skill_taxonomy_release_ready()
        """
    )


def _create_content_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_skill_seed_content_mutation()
        RETURNS trigger AS $$
        DECLARE
            content_revision_id uuid;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'governed Skill seed content is immutable';
            END IF;
            content_revision_id := NEW.revision_id;
            IF EXISTS (
                SELECT 1 FROM skill_taxonomy_releases release
                WHERE release.revision_id = content_revision_id
                  AND release.status = 'materializing'
            ) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'governed Skill seed content may only be inserted while materializing';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_governed_skill_categories_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON governed_skill_categories
        FOR EACH ROW EXECUTE FUNCTION reject_skill_seed_content_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_governed_skill_technologies_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON governed_skill_technologies
        FOR EACH ROW EXECUTE FUNCTION reject_skill_seed_content_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_governed_skill_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF EXISTS (
                    SELECT 1 FROM skill_taxonomy_releases release
                    WHERE release.revision_id = NEW.revision_id
                      AND release.status = 'materializing'
                ) THEN
                    RETURN NEW;
                END IF;
                IF NEW.origin = 'operator' AND EXISTS (
                    SELECT 1 FROM skill_taxonomy_active_revisions active
                    WHERE active.singleton_key = 'skill-taxonomy'
                      AND active.revision_id = NEW.revision_id
                ) THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'governed Skills may only be seeded while materializing or appended by an operator';
            END IF;
            IF TG_OP = 'UPDATE'
               AND OLD.origin = 'operator'
               AND OLD.created_by_audit_id IS NULL
               AND NEW.created_by_audit_id IS NOT NULL
               AND (to_jsonb(NEW) - 'created_by_audit_id') =
                   (to_jsonb(OLD) - 'created_by_audit_id')
            THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'governed Skills are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_governed_skills_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON governed_skills
        FOR EACH ROW EXECUTE FUNCTION guard_governed_skill_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION guard_governed_skill_alias_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'UPDATE'
               AND OLD.source = 'operator'
               AND OLD.created_by_audit_id IS NULL
               AND NEW.created_by_audit_id IS NOT NULL
               AND (to_jsonb(NEW) - 'created_by_audit_id') =
                   (to_jsonb(OLD) - 'created_by_audit_id')
            THEN
                RETURN NEW;
            END IF;
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'governed Skill aliases are immutable';
            END IF;
            IF EXISTS (
                SELECT 1 FROM skill_taxonomy_releases release
                WHERE release.revision_id = NEW.taxonomy_revision_id
                  AND release.status = 'materializing'
            ) THEN
                RETURN NEW;
            END IF;
            IF NEW.source = 'operator' AND EXISTS (
                SELECT 1 FROM skill_taxonomy_active_revisions active
                WHERE active.singleton_key = 'skill-taxonomy'
                  AND active.revision_id = NEW.taxonomy_revision_id
            ) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'operator aliases require the active Skill revision';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_governed_skill_aliases_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON governed_skill_aliases
        FOR EACH ROW EXECUTE FUNCTION guard_governed_skill_alias_mutation()
        """
    )


def _create_active_pointer_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION require_ready_skill_taxonomy_release()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Skill taxonomy active pointer cannot be deleted';
            END IF;
            IF TG_OP = 'INSERT' AND NEW.lock_version <> 1 THEN
                RAISE EXCEPTION 'Skill taxonomy active pointer must start at version 1';
            END IF;
            IF TG_OP = 'UPDATE' AND NEW.lock_version <> OLD.lock_version + 1 THEN
                RAISE EXCEPTION 'Skill taxonomy active pointer update is stale';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM skill_taxonomy_releases release
                JOIN governance_revisions governance
                  ON governance.id = release.revision_id
                WHERE release.revision_id = NEW.revision_id
                  AND release.content_hash = NEW.content_hash
                  AND release.status = 'ready'
                  AND release.expected_category_count = release.materialized_category_count
                  AND release.expected_technology_count = release.materialized_technology_count
                  AND release.expected_skill_count = release.materialized_skill_count
                  AND release.expected_alias_count = release.materialized_alias_count
                  AND governance.domain = 'skill-taxonomy'
                  AND governance.content_hash = NEW.content_hash
            ) THEN
                RAISE EXCEPTION 'Skill taxonomy active pointer requires a ready release';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_skill_taxonomy_active_ready
        BEFORE INSERT OR UPDATE OR DELETE ON skill_taxonomy_active_revisions
        FOR EACH ROW EXECUTE FUNCTION require_ready_skill_taxonomy_release()
        """
    )


def _create_decision_audit_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION require_skill_candidate_decision_audit()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.status <> 'pending' AND (
                NEW.decision_audit_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM governance_audit_events audit
                    WHERE audit.id = NEW.decision_audit_id
                      AND audit.domain = 'skill-governance'
                      AND audit.subject_type = 'skill-candidate'
                      AND audit.subject_id = NEW.id::text
                )
            ) THEN
                RAISE EXCEPTION 'resolved Skill Candidate requires its governance audit';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_skill_candidate_decision_audit
        AFTER INSERT OR UPDATE ON skill_candidates
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION require_skill_candidate_decision_audit()
        """
    )
    op.execute(
        """
        CREATE FUNCTION require_operator_skill_alias_audit()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.source = 'operator' AND (
                NEW.created_by_audit_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM governance_audit_events audit
                    WHERE audit.id = NEW.created_by_audit_id
                      AND audit.domain = 'skill-governance'
                      AND audit.subject_type = 'skill-candidate'
                      AND EXISTS (
                          SELECT 1 FROM skill_candidates candidate
                          WHERE candidate.id::text = audit.subject_id
                            AND candidate.taxonomy_revision_id = NEW.taxonomy_revision_id
                            AND candidate.resolved_skill_id = NEW.skill_id
                            AND candidate.decision_audit_id = audit.id
                      )
                )
            ) THEN
                RAISE EXCEPTION 'operator Skill alias requires governance audit';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_operator_skill_alias_audit
        AFTER INSERT OR UPDATE ON governed_skill_aliases
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION require_operator_skill_alias_audit()
        """
    )
    op.execute(
        """
        CREATE FUNCTION require_operator_skill_decision_audit()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.origin = 'operator' AND (
                NEW.created_by_audit_id IS NULL OR NOT EXISTS (
                    SELECT 1 FROM governance_audit_events audit
                    WHERE audit.id = NEW.created_by_audit_id
                      AND audit.domain = 'skill-governance'
                      AND audit.subject_type = 'skill-candidate'
                      AND EXISTS (
                          SELECT 1 FROM skill_candidates candidate
                          WHERE candidate.id::text = audit.subject_id
                            AND candidate.taxonomy_revision_id = NEW.revision_id
                            AND candidate.resolved_skill_id = NEW.id
                            AND candidate.decision_audit_id = audit.id
                      )
                )
            ) THEN
                RAISE EXCEPTION 'operator-created Skill requires governance audit';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE CONSTRAINT TRIGGER trg_operator_skill_decision_audit
        AFTER INSERT OR UPDATE ON governed_skills
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW EXECUTE FUNCTION require_operator_skill_decision_audit()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_operator_skill_alias_audit "
        "ON governed_skill_aliases"
    )
    op.execute("DROP FUNCTION IF EXISTS require_operator_skill_alias_audit()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_operator_skill_decision_audit ON governed_skills"
    )
    op.execute("DROP FUNCTION IF EXISTS require_operator_skill_decision_audit()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_skill_candidate_decision_audit ON skill_candidates"
    )
    op.execute("DROP FUNCTION IF EXISTS require_skill_candidate_decision_audit()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_skill_taxonomy_active_ready "
        "ON skill_taxonomy_active_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS require_ready_skill_taxonomy_release()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_governed_skill_aliases_immutable "
        "ON governed_skill_aliases"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_governed_skill_alias_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_governed_skills_immutable ON governed_skills"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_governed_skill_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_governed_skill_technologies_immutable "
        "ON governed_skill_technologies"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_governed_skill_categories_immutable "
        "ON governed_skill_categories"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_skill_seed_content_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_skill_taxonomy_release_ready_guard "
        "ON skill_taxonomy_releases"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_skill_taxonomy_release_ready()")

    op.drop_index("ix_governed_job_skills_filter", table_name="governed_job_skills")
    op.drop_index("ix_governed_job_skills_skill_id", table_name="governed_job_skills")
    op.drop_index(
        "ix_governed_job_skills_taxonomy_revision_id",
        table_name="governed_job_skills",
    )
    op.drop_index("ix_governed_job_skills_job_id", table_name="governed_job_skills")
    op.drop_table("governed_job_skills")

    op.drop_index(
        "ix_governed_job_skill_mentions_skill",
        table_name="governed_job_skill_mentions",
    )
    op.drop_index(
        "ix_governed_job_skill_mentions_candidate",
        table_name="governed_job_skill_mentions",
    )
    op.drop_index(
        "ux_governed_job_skill_mention_active_key",
        table_name="governed_job_skill_mentions",
    )
    op.drop_index(
        "ix_governed_job_skill_mentions_taxonomy_revision_id",
        table_name="governed_job_skill_mentions",
    )
    op.drop_index(
        "ix_governed_job_skill_mentions_job_id",
        table_name="governed_job_skill_mentions",
    )
    op.drop_table("governed_job_skill_mentions")

    op.drop_index("ix_skill_candidates_queue", table_name="skill_candidates")
    op.drop_index(
        "ix_skill_candidates_taxonomy_revision_id",
        table_name="skill_candidates",
    )
    op.drop_table("skill_candidates")

    op.drop_index(
        "ix_governed_skill_alias_lookup",
        table_name="governed_skill_aliases",
    )
    op.drop_index(
        "ix_governed_skill_aliases_skill_id",
        table_name="governed_skill_aliases",
    )
    op.drop_index(
        "ix_governed_skill_aliases_taxonomy_revision_id",
        table_name="governed_skill_aliases",
    )
    op.drop_table("governed_skill_aliases")

    op.drop_index("ix_governed_skills_active", table_name="governed_skills")
    op.drop_index("ix_governed_skills_technology_id", table_name="governed_skills")
    op.drop_index("ix_governed_skills_revision_id", table_name="governed_skills")
    op.drop_table("governed_skills")

    op.drop_index(
        "ix_governed_skill_technologies_category_id",
        table_name="governed_skill_technologies",
    )
    op.drop_index(
        "ix_governed_skill_technologies_revision_id",
        table_name="governed_skill_technologies",
    )
    op.drop_table("governed_skill_technologies")

    op.drop_index(
        "ix_governed_skill_categories_revision_id",
        table_name="governed_skill_categories",
    )
    op.drop_table("governed_skill_categories")
    op.drop_table("skill_taxonomy_active_revisions")
    op.drop_table("skill_taxonomy_releases")
