"""add Job Intelligence governance foundation

Revision ID: 20260718_210000
Revises: 20260718_180000
Create Date: 2026-07-18 21:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260718_210000"
down_revision = "20260718_180000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "governance_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(length=100), nullable=False),
        sa.Column("release_key", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="published",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status = 'published'",
            name="ck_governance_revision_published",
        ),
        sa.CheckConstraint(
            "content_hash ~ '^[0-9a-f]{64}$'",
            name="ck_governance_revision_content_hash",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "domain",
            "release_key",
            name="uq_governance_revision_release_key",
        ),
        sa.UniqueConstraint(
            "domain",
            "content_hash",
            name="uq_governance_revision_content_hash",
        ),
    )
    op.create_index(
        "ix_governance_revisions_domain",
        "governance_revisions",
        ["domain"],
    )

    op.create_table(
        "governance_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(length=100), nullable=False),
        sa.Column("subject_type", sa.String(length=100), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("before_summary", sa.JSON(), nullable=False),
        sa.Column("after_summary", sa.JSON(), nullable=False),
        sa.Column("evidence_refs", sa.JSON(), nullable=False),
        sa.Column("correlation_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "actor = 'local-operator'",
            name="ck_governance_audit_actor_local_operator",
        ),
        sa.CheckConstraint(
            "command_hash ~ '^[0-9a-f]{64}$'",
            name="ck_governance_audit_command_hash",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_governance_audit_domain_created_id",
        "governance_audit_events",
        ["domain", "created_at", "id"],
    )
    op.create_index(
        "ix_governance_audit_subject_created",
        "governance_audit_events",
        ["subject_type", "subject_id", "created_at"],
    )

    op.create_table(
        "governance_idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("command_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "audit_event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("result_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "command_hash ~ '^[0-9a-f]{64}$'",
            name="ck_governance_idempotency_command_hash",
        ),
        sa.ForeignKeyConstraint(
            ["audit_event_id"],
            ["governance_audit_events.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "domain",
            "idempotency_key",
            name="uq_governance_idempotency_domain_key",
        ),
    )
    op.create_index(
        "ix_governance_idempotency_records_domain",
        "governance_idempotency_records",
        ["domain"],
    )

    op.execute(
        """
        CREATE FUNCTION reject_governance_revision_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'governance revisions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_governance_revisions_immutable
        BEFORE UPDATE OR DELETE ON governance_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_governance_revision_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_governance_audit_event_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'governance audit events are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_governance_audit_events_append_only
        BEFORE UPDATE OR DELETE ON governance_audit_events
        FOR EACH ROW EXECUTE FUNCTION reject_governance_audit_event_mutation()
        """
    )
    op.execute(
        """
        CREATE FUNCTION reject_governance_idempotency_record_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'governance idempotency records are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_governance_idempotency_records_immutable
        BEFORE UPDATE OR DELETE ON governance_idempotency_records
        FOR EACH ROW EXECUTE FUNCTION reject_governance_idempotency_record_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_governance_idempotency_records_immutable "
        "ON governance_idempotency_records"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS reject_governance_idempotency_record_mutation()"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_governance_audit_events_append_only "
        "ON governance_audit_events"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_governance_audit_event_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_governance_revisions_immutable "
        "ON governance_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_governance_revision_mutation()")

    op.drop_index(
        "ix_governance_idempotency_records_domain",
        table_name="governance_idempotency_records",
    )
    op.drop_table("governance_idempotency_records")

    op.drop_index(
        "ix_governance_audit_subject_created",
        table_name="governance_audit_events",
    )
    op.drop_index(
        "ix_governance_audit_domain_created_id",
        table_name="governance_audit_events",
    )
    op.drop_table("governance_audit_events")

    op.drop_index(
        "ix_governance_revisions_domain",
        table_name="governance_revisions",
    )
    op.drop_table("governance_revisions")
