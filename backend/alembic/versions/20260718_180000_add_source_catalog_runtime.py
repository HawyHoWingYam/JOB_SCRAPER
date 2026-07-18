"""add authoritative source catalog runtime

Revision ID: 20260718_180000
Revises: 20260718_150000
Create Date: 2026-07-18 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_180000"
down_revision = "20260718_150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_catalog_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("base_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("normalized_payload", sa.JSON(), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("diff", sa.JSON(), nullable=False),
        sa.Column("validation_summary", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="discovered"),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_catalog_candidates_source_site",
        "source_catalog_candidates",
        ["source_site"],
    )
    op.create_index(
        "ix_source_catalog_candidates_base_revision_id",
        "source_catalog_candidates",
        ["base_revision_id"],
    )
    op.create_index(
        "ix_source_catalog_candidates_state",
        "source_catalog_candidates",
        ["state"],
    )
    op.create_index(
        "ux_source_catalog_candidates_active_fingerprint",
        "source_catalog_candidates",
        ["source_site", "fingerprint"],
        unique=True,
        postgresql_where=sa.text("state <> 'superseded'"),
    )

    op.create_table(
        "source_catalog_validation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("validation_kind", sa.String(length=32), nullable=False),
        sa.Column("node_key", sa.String(length=255), nullable=True),
        sa.Column("classification_id", sa.String(length=255), nullable=True),
        sa.Column("expected_target_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("claimed_by", sa.String(length=255), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("error", sa.JSON(), nullable=True),
        sa.Column("manual_action", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["source_catalog_candidates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "candidate_id",
            "validation_kind",
            "expected_target_hash",
            "attempt",
            name="uq_source_catalog_validation_attempt",
        ),
    )
    op.create_index(
        "ix_source_catalog_validation_runs_candidate_id",
        "source_catalog_validation_runs",
        ["candidate_id"],
    )
    op.create_index(
        "ix_source_catalog_validation_runs_validation_kind",
        "source_catalog_validation_runs",
        ["validation_kind"],
    )
    op.create_index(
        "ix_source_catalog_validation_runs_status",
        "source_catalog_validation_runs",
        ["status"],
    )

    op.create_table(
        "source_catalog_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("normalized_payload", sa.JSON(), nullable=False),
        sa.Column("source_payload", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("predecessor_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("publication_metadata", sa.JSON(), nullable=False),
        sa.Column("published_by", sa.String(length=255), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["source_catalog_candidates.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_revision_id"],
            ["source_catalog_revisions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("candidate_id"),
        sa.UniqueConstraint(
            "source_site", "sequence", name="uq_source_catalog_revision_sequence"
        ),
        sa.UniqueConstraint(
            "source_site", "fingerprint", name="uq_source_catalog_revision_fingerprint"
        ),
    )
    op.create_index(
        "ix_source_catalog_revisions_source_site",
        "source_catalog_revisions",
        ["source_site"],
    )

    op.create_table(
        "source_catalog_active_revisions",
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("updated_by", sa.String(length=255), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["source_catalog_revisions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("source_site"),
        sa.UniqueConstraint("revision_id"),
    )

    op.create_table(
        "source_catalog_change_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("base_active_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("automation_impact_digest", sa.String(length=64), nullable=False),
        sa.Column("automation_impact", sa.JSON(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation IN ('publish', 'rollback')",
            name="ck_source_catalog_review_operation",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["source_catalog_candidates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["target_revision_id"], ["source_catalog_revisions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_source_catalog_change_reviews_operation",
        "source_catalog_change_reviews",
        ["operation"],
    )
    op.create_index(
        "ix_source_catalog_change_reviews_source_site",
        "source_catalog_change_reviews",
        ["source_site"],
    )

    op.create_table(
        "source_catalog_publications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("revision_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("previous_revision_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation IN ('publish', 'rollback')",
            name="ck_source_catalog_publication_operation",
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"], ["source_catalog_revisions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["review_id"], ["source_catalog_change_reviews.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("review_id"),
    )
    op.create_index(
        "ix_source_catalog_publications_source_site",
        "source_catalog_publications",
        ["source_site"],
    )
    op.execute(
        """
        CREATE FUNCTION reject_source_catalog_revision_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'source catalog revisions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_catalog_revisions_immutable
        BEFORE UPDATE OR DELETE ON source_catalog_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_source_catalog_revision_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_source_catalog_candidate_payload_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF NEW.source_site IS DISTINCT FROM OLD.source_site
               OR NEW.base_revision_id IS DISTINCT FROM OLD.base_revision_id
               OR NEW.fingerprint IS DISTINCT FROM OLD.fingerprint
               OR NEW.normalized_payload::text IS DISTINCT FROM OLD.normalized_payload::text
               OR NEW.source_payload::text IS DISTINCT FROM OLD.source_payload::text
               OR NEW.provenance::text IS DISTINCT FROM OLD.provenance::text
               OR NEW.diff::text IS DISTINCT FROM OLD.diff::text THEN
                RAISE EXCEPTION 'source catalog candidate payload is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_catalog_candidates_payload_immutable
        BEFORE UPDATE ON source_catalog_candidates
        FOR EACH ROW EXECUTE FUNCTION reject_source_catalog_candidate_payload_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_source_catalog_candidates_payload_immutable "
        "ON source_catalog_candidates"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_source_catalog_candidate_payload_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_source_catalog_revisions_immutable "
        "ON source_catalog_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_source_catalog_revision_mutation()")

    op.drop_index(
        "ix_source_catalog_publications_source_site",
        table_name="source_catalog_publications",
    )
    op.drop_table("source_catalog_publications")

    op.drop_index(
        "ix_source_catalog_change_reviews_source_site",
        table_name="source_catalog_change_reviews",
    )
    op.drop_index(
        "ix_source_catalog_change_reviews_operation",
        table_name="source_catalog_change_reviews",
    )
    op.drop_table("source_catalog_change_reviews")

    op.drop_table("source_catalog_active_revisions")

    op.drop_index(
        "ix_source_catalog_revisions_source_site",
        table_name="source_catalog_revisions",
    )
    op.drop_table("source_catalog_revisions")

    op.drop_index(
        "ix_source_catalog_validation_runs_status",
        table_name="source_catalog_validation_runs",
    )
    op.drop_index(
        "ix_source_catalog_validation_runs_validation_kind",
        table_name="source_catalog_validation_runs",
    )
    op.drop_index(
        "ix_source_catalog_validation_runs_candidate_id",
        table_name="source_catalog_validation_runs",
    )
    op.drop_table("source_catalog_validation_runs")

    op.drop_index(
        "ux_source_catalog_candidates_active_fingerprint",
        table_name="source_catalog_candidates",
    )
    op.drop_index(
        "ix_source_catalog_candidates_state",
        table_name="source_catalog_candidates",
    )
    op.drop_index(
        "ix_source_catalog_candidates_base_revision_id",
        table_name="source_catalog_candidates",
    )
    op.drop_index(
        "ix_source_catalog_candidates_source_site",
        table_name="source_catalog_candidates",
    )
    op.drop_table("source_catalog_candidates")
