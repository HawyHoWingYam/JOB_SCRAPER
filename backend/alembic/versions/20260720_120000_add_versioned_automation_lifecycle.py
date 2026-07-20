"""add versioned Automation lifecycle and preserved execution history

Revision ID: 20260720_120000
Revises: 20260719_160000
Create Date: 2026-07-20 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720_120000"
down_revision = "20260719_160000"
branch_labels = None
depends_on = None


_SCHEDULE_INSTANTS = (
    "last_run_at",
    "next_run_at",
    "created_at",
    "updated_at",
)
_EXECUTION_INSTANTS = ("started_at", "completed_at", "created_at")
_HEARTBEAT_INSTANTS = ("started_at", "last_heartbeat_at", "last_reconcile_at")


def _interpret_naive_instants_as_utc(
    table_name: str,
    columns: tuple[str, ...],
) -> None:
    for column_name in columns:
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = '{table_name}'
                  AND column_name = '{column_name}'
                  AND data_type = 'timestamp without time zone'
              ) THEN
                EXECUTE 'ALTER TABLE {table_name} ALTER COLUMN {column_name} '
                  || 'TYPE TIMESTAMP WITH TIME ZONE USING '
                  || '{column_name} AT TIME ZONE ''UTC''';
              END IF;
            END $$
            """
        )


def _return_instants_to_naive_utc(
    table_name: str,
    columns: tuple[str, ...],
) -> None:
    for column_name in columns:
        op.execute(
            f"""
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = '{table_name}'
                  AND column_name = '{column_name}'
                  AND data_type = 'timestamp with time zone'
              ) THEN
                EXECUTE 'ALTER TABLE {table_name} ALTER COLUMN {column_name} '
                  || 'TYPE TIMESTAMP WITHOUT TIME ZONE USING '
                  || '{column_name} AT TIME ZONE ''UTC''';
              END IF;
            END $$
            """
        )


def upgrade() -> None:
    op.add_column(
        "scrape_schedules",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("lifecycle_state", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("scope_contract", sa.JSON(), nullable=True),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("listing_page_depth", sa.Integer(), nullable=True),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("listing_run_page_cap", sa.Integer(), nullable=True),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("detail_run_cap", sa.Integer(), nullable=True),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("detail_limit_kind", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("detail_backlog_scope", sa.JSON(), nullable=True),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("scope_review_reason", sa.JSON(), nullable=True),
    )
    op.add_column(
        "scrape_schedules",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE scrape_schedules SET lifecycle_state = "
        "CASE WHEN COALESCE(is_active, false) THEN 'active' ELSE 'paused' END "
        "WHERE lifecycle_state IS NULL"
    )
    op.execute(
        "UPDATE scrape_schedules SET timezone = 'Asia/Hong_Kong' "
        "WHERE timezone IS NULL OR trim(timezone) = ''"
    )
    op.execute(
        "UPDATE scrape_schedules SET created_at = CURRENT_TIMESTAMP "
        "WHERE created_at IS NULL"
    )
    op.execute(
        "UPDATE scrape_schedules SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP) "
        "WHERE updated_at IS NULL"
    )
    op.execute(
        "UPDATE scrape_schedules SET is_active = (lifecycle_state = 'active')"
    )
    op.alter_column(
        "scrape_schedules",
        "lifecycle_state",
        existing_type=sa.String(length=32),
        nullable=False,
        server_default="paused",
    )
    op.alter_column(
        "scrape_schedules",
        "timezone",
        existing_type=sa.String(length=50),
        nullable=False,
        server_default="Asia/Hong_Kong",
    )
    op.alter_column(
        "scrape_schedules",
        "is_active",
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.text("true"),
    )
    op.alter_column(
        "scrape_schedules",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )
    op.alter_column(
        "scrape_schedules",
        "updated_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_scrape_schedules_revision_positive",
        "scrape_schedules",
        "revision > 0",
    )
    op.create_check_constraint(
        "ck_scrape_schedules_lifecycle_state",
        "scrape_schedules",
        "lifecycle_state IN ('active', 'paused', 'archived', "
        "'scope_review_required')",
    )
    op.create_check_constraint(
        "ck_scrape_schedules_archived_at",
        "scrape_schedules",
        "(lifecycle_state = 'archived' AND archived_at IS NOT NULL) OR "
        "(lifecycle_state <> 'archived' AND archived_at IS NULL)",
    )
    op.create_index(
        "ix_scrape_schedules_lifecycle_state",
        "scrape_schedules",
        ["lifecycle_state"],
    )
    op.create_index(
        "ix_scrape_schedules_lifecycle_next_run",
        "scrape_schedules",
        ["lifecycle_state", "next_run_at"],
    )

    op.create_table(
        "automation_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_automation_revisions_revision_positive",
        ),
        sa.CheckConstraint(
            "length(snapshot_fingerprint) = 64",
            name="ck_automation_revisions_snapshot_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"],
            ["scrape_schedules.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "automation_id",
            "revision",
            name="uq_automation_revisions_automation_revision",
        ),
    )
    op.create_index(
        "ix_automation_revisions_automation_id",
        "automation_revisions",
        ["automation_id"],
    )
    op.create_index(
        "ix_automation_revisions_automation_created",
        "automation_revisions",
        ["automation_id", "created_at"],
    )

    op.create_table(
        "automation_delete_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "automation_id_snapshot",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("impact_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("impact_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "expected_revision > 0",
            name="ck_automation_delete_reviews_revision_positive",
        ),
        sa.CheckConstraint(
            "length(token_hash) = 64 AND length(impact_fingerprint) = 64",
            name="ck_automation_delete_reviews_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"],
            ["scrape_schedules.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_automation_delete_reviews_automation_id",
        "automation_delete_reviews",
        ["automation_id"],
    )
    op.create_index(
        "ix_automation_delete_reviews_automation_expiry",
        "automation_delete_reviews",
        ["automation_id_snapshot", "expires_at"],
    )

    op.add_column(
        "schedule_executions",
        sa.Column(
            "automation_id_snapshot",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "schedule_executions",
        sa.Column("automation_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "schedule_executions",
        sa.Column("automation_snapshot", sa.JSON(), nullable=True),
    )
    op.create_index(
        "ix_schedule_executions_automation_id_snapshot",
        "schedule_executions",
        ["automation_id_snapshot"],
    )
    op.execute(
        "UPDATE schedule_executions SET automation_id_snapshot = schedule_id "
        "WHERE automation_id_snapshot IS NULL AND schedule_id IS NOT NULL"
    )
    op.execute(
        """
        DO $$
        DECLARE schedule_fk_name text;
        BEGIN
          FOR schedule_fk_name IN
            SELECT tc.constraint_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_schema = kcu.constraint_schema
             AND tc.constraint_name = kcu.constraint_name
             AND tc.table_name = kcu.table_name
            WHERE tc.table_schema = current_schema()
              AND tc.table_name = 'schedule_executions'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'schedule_id'
          LOOP
            EXECUTE 'ALTER TABLE schedule_executions DROP CONSTRAINT '
              || quote_ident(schedule_fk_name);
          END LOOP;
        END $$
        """
    )
    op.alter_column(
        "schedule_executions",
        "schedule_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_schedule_executions_schedule_id_scrape_schedules",
        "schedule_executions",
        "scrape_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "UPDATE schedule_executions SET created_at = COALESCE(started_at, "
        "CURRENT_TIMESTAMP) WHERE created_at IS NULL"
    )
    op.alter_column(
        "schedule_executions",
        "created_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )

    _interpret_naive_instants_as_utc("scrape_schedules", _SCHEDULE_INSTANTS)
    _interpret_naive_instants_as_utc("schedule_executions", _EXECUTION_INSTANTS)
    _interpret_naive_instants_as_utc(
        "scheduler_runtime_heartbeats",
        _HEARTBEAT_INSTANTS,
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_automation_revision_update()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'Automation revisions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_automation_revisions_immutable
        BEFORE UPDATE ON automation_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_automation_revision_update()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_automation_revisions_immutable "
        "ON automation_revisions"
    )
    op.execute("DROP FUNCTION IF EXISTS reject_automation_revision_update()")

    _return_instants_to_naive_utc(
        "scheduler_runtime_heartbeats",
        _HEARTBEAT_INSTANTS,
    )
    _return_instants_to_naive_utc("schedule_executions", _EXECUTION_INSTANTS)
    _return_instants_to_naive_utc("scrape_schedules", _SCHEDULE_INSTANTS)

    op.drop_constraint(
        "fk_schedule_executions_schedule_id_scrape_schedules",
        "schedule_executions",
        type_="foreignkey",
    )
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM schedule_executions WHERE schedule_id IS NULL
          ) THEN
            RAISE EXCEPTION
              'Cannot downgrade Automation history after detached executions; '
              'restore the pre-cutover database backup instead';
          END IF;
        END $$
        """
    )
    op.alter_column(
        "schedule_executions",
        "schedule_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_schedule_executions_schedule_id_scrape_schedules",
        "schedule_executions",
        "scrape_schedules",
        ["schedule_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_index(
        "ix_schedule_executions_automation_id_snapshot",
        table_name="schedule_executions",
    )
    op.drop_column("schedule_executions", "automation_snapshot")
    op.drop_column("schedule_executions", "automation_revision")
    op.drop_column("schedule_executions", "automation_id_snapshot")

    op.drop_index(
        "ix_automation_delete_reviews_automation_expiry",
        table_name="automation_delete_reviews",
    )
    op.drop_index(
        "ix_automation_delete_reviews_automation_id",
        table_name="automation_delete_reviews",
    )
    op.drop_table("automation_delete_reviews")

    op.drop_index(
        "ix_automation_revisions_automation_created",
        table_name="automation_revisions",
    )
    op.drop_index(
        "ix_automation_revisions_automation_id",
        table_name="automation_revisions",
    )
    op.drop_table("automation_revisions")

    op.drop_index(
        "ix_scrape_schedules_lifecycle_next_run",
        table_name="scrape_schedules",
    )
    op.drop_index(
        "ix_scrape_schedules_lifecycle_state",
        table_name="scrape_schedules",
    )
    op.drop_constraint(
        "ck_scrape_schedules_archived_at",
        "scrape_schedules",
        type_="check",
    )
    op.drop_constraint(
        "ck_scrape_schedules_lifecycle_state",
        "scrape_schedules",
        type_="check",
    )
    op.drop_constraint(
        "ck_scrape_schedules_revision_positive",
        "scrape_schedules",
        type_="check",
    )
    op.drop_column("scrape_schedules", "archived_at")
    op.drop_column("scrape_schedules", "scope_review_reason")
    op.drop_column("scrape_schedules", "detail_backlog_scope")
    op.drop_column("scrape_schedules", "detail_limit_kind")
    op.drop_column("scrape_schedules", "detail_run_cap")
    op.drop_column("scrape_schedules", "listing_run_page_cap")
    op.drop_column("scrape_schedules", "listing_page_depth")
    op.drop_column("scrape_schedules", "scope_contract")
    op.drop_column("scrape_schedules", "lifecycle_state")
    op.drop_column("scrape_schedules", "revision")
