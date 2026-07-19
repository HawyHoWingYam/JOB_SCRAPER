"""add governed Company Industry taxonomy

Revision ID: 20260719_120000
Revises: 20260719_010000
Create Date: 2026-07-19 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260719_120000"
down_revision = "20260719_010000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_industry_taxonomy_releases",
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("standard", sa.String(length=32), nullable=False),
        sa.Column("release", sa.String(length=32), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("expected_counts", sa.JSON(), nullable=False),
        sa.Column(
            "materialized_counts",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column("expected_total", sa.Integer(), nullable=False),
        sa.Column(
            "materialized_total",
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
            name="ck_company_industry_release_hash",
        ),
        sa.CheckConstraint(
            "status IN ('materializing', 'ready')",
            name="ck_company_industry_release_status",
        ),
        sa.CheckConstraint(
            "expected_total >= 0 AND materialized_total >= 0",
            name="ck_company_industry_release_counts",
        ),
        sa.CheckConstraint(
            "(status = 'materializing' AND ready_at IS NULL) OR "
            "(status = 'ready' AND ready_at IS NOT NULL "
            "AND expected_total = materialized_total)",
            name="ck_company_industry_release_ready",
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
            name="uq_company_industry_release_hash",
        ),
    )

    op.create_table(
        "company_industry_active_revisions",
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
            "singleton_key = 'company-industry'",
            name="ck_company_industry_active_singleton",
        ),
        sa.CheckConstraint(
            "lock_version > 0",
            name="ck_company_industry_active_version",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id", "content_hash"],
            [
                "company_industry_taxonomy_releases.revision_id",
                "company_industry_taxonomy_releases.content_hash",
            ],
            name="fk_company_industry_active_release",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("singleton_key"),
        sa.UniqueConstraint(
            "revision_id",
            name="uq_company_industry_active_revision",
        ),
    )

    op.create_table(
        "company_industry_taxonomy_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=6), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("label_en", sa.String(length=500), nullable=False),
        sa.Column("label_zh_hant", sa.String(length=500), nullable=False),
        sa.Column("label_zh_hans", sa.String(length=500), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.Column(
            "is_assignable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "source_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.CheckConstraint(
            "level IN ('section', 'division', 'group', 'class', 'subclass')",
            name="ck_company_industry_node_level",
        ),
        sa.CheckConstraint(
            "(level = 'section' AND parent_id IS NULL) OR "
            "(level <> 'section' AND parent_id IS NOT NULL)",
            name="ck_company_industry_node_parent",
        ),
        sa.CheckConstraint(
            "length(trim(code)) > 0 AND length(trim(label_en)) > 0 "
            "AND length(trim(label_zh_hant)) > 0 "
            "AND length(trim(label_zh_hans)) > 0",
            name="ck_company_industry_node_labels",
        ),
        sa.CheckConstraint(
            "source_order > 0",
            name="ck_company_industry_node_order",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["company_industry_taxonomy_releases.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id", "revision_id"],
            [
                "company_industry_taxonomy_nodes.id",
                "company_industry_taxonomy_nodes.revision_id",
            ],
            name="fk_company_industry_node_parent_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "revision_id",
            name="uq_company_industry_node_id_revision",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "code",
            name="uq_company_industry_node_code",
        ),
        sa.UniqueConstraint(
            "revision_id",
            "source_order",
            name="uq_company_industry_node_order",
        ),
    )
    op.create_index(
        "ix_company_industry_taxonomy_nodes_revision_id",
        "company_industry_taxonomy_nodes",
        ["revision_id"],
    )
    op.create_index(
        "ix_company_industry_nodes_parent",
        "company_industry_taxonomy_nodes",
        ["revision_id", "parent_id", "source_order"],
    )

    op.create_table(
        "company_industry_crosswalk_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("hsic_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_standard", sa.String(length=32), nullable=False),
        sa.Column("target_release", sa.String(length=64), nullable=False),
        sa.Column("target_code", sa.String(length=64), nullable=False),
        sa.Column("cardinality", sa.String(length=32), nullable=False),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("source_order", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "cardinality IN ('one_to_one', 'one_to_many', 'many_to_one', 'many_to_many')",
            name="ck_company_industry_crosswalk_cardinality",
        ),
        sa.CheckConstraint(
            "method IN ('official', 'project_validated')",
            name="ck_company_industry_crosswalk_method",
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_company_industry_crosswalk_confidence",
        ),
        sa.CheckConstraint(
            "source_order > 0",
            name="ck_company_industry_crosswalk_order",
        ),
        sa.ForeignKeyConstraint(
            ["hsic_node_id", "taxonomy_revision_id"],
            [
                "company_industry_taxonomy_nodes.id",
                "company_industry_taxonomy_nodes.revision_id",
            ],
            name="fk_company_industry_crosswalk_hsic_node",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "taxonomy_revision_id",
            "hsic_node_id",
            "target_standard",
            "target_release",
            "target_code",
            name="uq_company_industry_crosswalk_edge",
        ),
    )

    op.create_table(
        "source_industry_mappings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("key_kind", sa.String(length=16), nullable=False),
        sa.Column("raw_value", sa.String(length=500), nullable=False),
        sa.Column("normalized_key", sa.String(length=500), nullable=False),
        sa.Column(
            "taxonomy_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approved_by", sa.String(length=64), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "decision_audit_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "key_kind IN ('code', 'label')",
            name="ck_source_industry_mapping_key_kind",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded', 'retired')",
            name="ck_source_industry_mapping_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND superseded_at IS NULL) OR "
            "(status IN ('superseded', 'retired') AND superseded_at IS NOT NULL)",
            name="ck_source_industry_mapping_superseded",
        ),
        sa.CheckConstraint(
            "approved_by = 'local-operator' AND lock_version > 0",
            name="ck_source_industry_mapping_approval",
        ),
        sa.ForeignKeyConstraint(
            ["target_node_id", "taxonomy_revision_id"],
            [
                "company_industry_taxonomy_nodes.id",
                "company_industry_taxonomy_nodes.revision_id",
            ],
            name="fk_source_industry_mapping_target",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_audit_id"],
            ["governance_audit_events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_source_industry_mapping_active",
        "source_industry_mappings",
        ["source_site", "key_kind", "normalized_key"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "company_industry_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mapping_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("method", sa.String(length=32), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("breadcrumb", sa.JSON(), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("primary_basis", sa.String(length=32), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "method IN ('authoritative_code', 'reviewed_mapping', 'operator')",
            name="ck_company_industry_assignment_method",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'superseded')",
            name="ck_company_industry_assignment_status",
        ),
        sa.CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$'",
            name="ck_company_industry_assignment_hash",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND superseded_at IS NULL) OR "
            "(status = 'superseded' AND superseded_at IS NOT NULL)",
            name="ck_company_industry_assignment_superseded",
        ),
        sa.CheckConstraint(
            "(is_primary AND primary_basis IN ('authoritative_source', 'operator')) OR "
            "(NOT is_primary AND primary_basis IS NULL)",
            name="ck_company_industry_assignment_primary_basis",
        ),
        sa.CheckConstraint(
            "lock_version > 0",
            name="ck_company_industry_assignment_version",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["node_id", "taxonomy_revision_id"],
            [
                "company_industry_taxonomy_nodes.id",
                "company_industry_taxonomy_nodes.revision_id",
            ],
            name="fk_company_industry_assignment_node",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_id"],
            ["source_industry_mappings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_industry_assignments_company_id",
        "company_industry_assignments",
        ["company_id"],
    )
    op.create_index(
        "ix_company_industry_assignments_node",
        "company_industry_assignments",
        ["taxonomy_revision_id", "node_id"],
    )
    op.create_index(
        "ux_company_industry_assignment_active_node",
        "company_industry_assignments",
        ["company_id", "node_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "ux_company_industry_assignment_primary",
        "company_industry_assignments",
        ["company_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active' AND is_primary"),
    )

    op.create_table(
        "company_industry_review_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "taxonomy_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("source_site", sa.String(length=32), nullable=True),
        sa.Column("key_kind", sa.String(length=16), nullable=True),
        sa.Column("raw_value", sa.String(length=500), nullable=True),
        sa.Column("normalized_key", sa.String(length=500), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column(
            "recommendations",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "decision_audit_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mapping_id", postgresql.UUID(as_uuid=True), nullable=True),
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
            "status IN ('active', 'assigned', 'insufficient_evidence', "
            "'not_company_industry', 'superseded')",
            name="ck_company_industry_review_status",
        ),
        sa.CheckConstraint(
            "reason IN ('taxonomy_not_active', 'unmapped_source_evidence', "
            "'manual_evidence', 'ai_recommendation', 'invalid_hsic_code', "
            "'conflicting_hsic_codes', 'conflicting_source_mapping', "
            "'not_company_industry')",
            name="ck_company_industry_review_reason",
        ),
        sa.CheckConstraint(
            "evidence_hash ~ '^[0-9a-f]{64}$'",
            name="ck_company_industry_review_hash",
        ),
        sa.CheckConstraint(
            "lock_version > 0",
            name="ck_company_industry_review_version",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND resolved_at IS NULL) OR "
            "(status <> 'active' AND resolved_at IS NOT NULL)",
            name="ck_company_industry_review_resolution",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_revision_id"],
            ["company_industry_taxonomy_releases.revision_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_audit_id"],
            ["governance_audit_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["company_industry_assignments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mapping_id"],
            ["source_industry_mappings.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_company_industry_review_items_company_id",
        "company_industry_review_items",
        ["company_id"],
    )
    op.create_index(
        "ix_company_industry_review_status_created",
        "company_industry_review_items",
        ["status", "created_at", "id"],
    )
    op.create_index(
        "ux_company_industry_review_active_evidence",
        "company_industry_review_items",
        ["company_id", "evidence_hash"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    _create_release_guards()
    _create_immutable_content_guards()
    _create_active_pointer_guards()


def _create_release_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION guard_company_industry_release_ready()
        RETURNS trigger AS $$
        DECLARE
            actual_counts jsonb;
            actual_total integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'ready Company Industry releases are immutable';
            END IF;
            IF TG_OP = 'UPDATE' AND OLD.status = 'ready' THEN
                RAISE EXCEPTION 'ready Company Industry releases are immutable';
            END IF;
            IF NEW.status = 'ready' THEN
                SELECT jsonb_build_object(
                    'section', count(*) FILTER (WHERE level = 'section'),
                    'division', count(*) FILTER (WHERE level = 'division'),
                    'group', count(*) FILTER (WHERE level = 'group'),
                    'class', count(*) FILTER (WHERE level = 'class'),
                    'subclass', count(*) FILTER (WHERE level = 'subclass')
                ), count(*)
                INTO actual_counts, actual_total
                FROM company_industry_taxonomy_nodes
                WHERE revision_id = NEW.revision_id;
                IF actual_counts <> NEW.expected_counts::jsonb
                   OR actual_counts <> NEW.materialized_counts::jsonb
                   OR actual_total <> NEW.expected_total
                   OR actual_total <> NEW.materialized_total
                THEN
                    RAISE EXCEPTION 'ready Company Industry release counts do not match materialized nodes';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_company_industry_release_ready_guard
        BEFORE INSERT OR UPDATE OR DELETE ON company_industry_taxonomy_releases
        FOR EACH ROW EXECUTE FUNCTION guard_company_industry_release_ready()
        """
    )


def _create_immutable_content_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION reject_company_industry_content_mutation()
        RETURNS trigger AS $$
        DECLARE
            content_revision_id uuid;
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF TG_TABLE_NAME = 'company_industry_taxonomy_nodes' THEN
                    content_revision_id := NEW.revision_id;
                ELSE
                    content_revision_id := NEW.taxonomy_revision_id;
                END IF;
                IF EXISTS (
                    SELECT 1 FROM company_industry_taxonomy_releases release
                    WHERE release.revision_id = content_revision_id
                      AND release.status = 'materializing'
                ) THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION 'Company Industry content may only be inserted while materializing';
            END IF;
            RAISE EXCEPTION 'Company Industry taxonomy content is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_company_industry_nodes_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON company_industry_taxonomy_nodes
        FOR EACH ROW EXECUTE FUNCTION reject_company_industry_content_mutation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_company_industry_crosswalks_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON company_industry_crosswalk_edges
        FOR EACH ROW EXECUTE FUNCTION reject_company_industry_content_mutation()
        """
    )


def _create_active_pointer_guards() -> None:
    op.execute(
        """
        CREATE FUNCTION require_ready_company_industry_release()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Company Industry active pointer cannot be deleted';
            END IF;
            IF TG_OP = 'INSERT' AND NEW.lock_version <> 1 THEN
                RAISE EXCEPTION 'Company Industry active pointer must start at version 1';
            END IF;
            IF TG_OP = 'UPDATE' AND NEW.lock_version <> OLD.lock_version + 1 THEN
                RAISE EXCEPTION 'Company Industry active pointer update is stale';
            END IF;
            IF NOT EXISTS (
                SELECT 1
                FROM company_industry_taxonomy_releases release
                JOIN governance_revisions governance
                  ON governance.id = release.revision_id
                WHERE release.revision_id = NEW.revision_id
                  AND release.content_hash = NEW.content_hash
                  AND release.status = 'ready'
                  AND release.expected_counts::jsonb = release.materialized_counts::jsonb
                  AND release.expected_total = release.materialized_total
                  AND governance.domain = 'company-industry'
                  AND governance.content_hash = NEW.content_hash
            ) THEN
                RAISE EXCEPTION 'Company Industry active pointer requires a ready release';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_company_industry_active_ready
        BEFORE INSERT OR UPDATE OR DELETE ON company_industry_active_revisions
        FOR EACH ROW EXECUTE FUNCTION require_ready_company_industry_release()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_company_industry_active_ready "
        "ON company_industry_active_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS require_ready_company_industry_release()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_company_industry_crosswalks_immutable "
        "ON company_industry_crosswalk_edges"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_company_industry_nodes_immutable "
        "ON company_industry_taxonomy_nodes"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_company_industry_content_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_company_industry_release_ready_guard "
        "ON company_industry_taxonomy_releases"
    )
    op.execute("DROP FUNCTION IF EXISTS guard_company_industry_release_ready()")

    op.drop_index(
        "ux_company_industry_review_active_evidence",
        table_name="company_industry_review_items",
    )
    op.drop_index(
        "ix_company_industry_review_status_created",
        table_name="company_industry_review_items",
    )
    op.drop_index(
        "ix_company_industry_review_items_company_id",
        table_name="company_industry_review_items",
    )
    op.drop_table("company_industry_review_items")

    op.drop_index(
        "ux_company_industry_assignment_primary",
        table_name="company_industry_assignments",
    )
    op.drop_index(
        "ux_company_industry_assignment_active_node",
        table_name="company_industry_assignments",
    )
    op.drop_index(
        "ix_company_industry_assignments_node",
        table_name="company_industry_assignments",
    )
    op.drop_index(
        "ix_company_industry_assignments_company_id",
        table_name="company_industry_assignments",
    )
    op.drop_table("company_industry_assignments")

    op.drop_index(
        "ux_source_industry_mapping_active",
        table_name="source_industry_mappings",
    )
    op.drop_table("source_industry_mappings")
    op.drop_table("company_industry_crosswalk_edges")

    op.drop_index(
        "ix_company_industry_nodes_parent",
        table_name="company_industry_taxonomy_nodes",
    )
    op.drop_index(
        "ix_company_industry_taxonomy_nodes_revision_id",
        table_name="company_industry_taxonomy_nodes",
    )
    op.drop_table("company_industry_taxonomy_nodes")
    op.drop_table("company_industry_active_revisions")
    op.drop_table("company_industry_taxonomy_releases")
