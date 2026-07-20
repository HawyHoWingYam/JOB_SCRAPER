"""add immutable Crawl Dispatch Plans and execution authority links

Revision ID: 20260720_180000
Revises: 20260720_120000
Create Date: 2026-07-20 18:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260720_180000"
down_revision = "20260720_120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crawl_dispatch_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("crawl_phase", sa.String(length=32), nullable=False),
        sa.Column("trigger_kind", sa.String(length=32), nullable=False),
        sa.Column("automation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "automation_id_snapshot",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("expected_automation_revision", sa.Integer(), nullable=True),
        sa.Column(
            "catalog_revision_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("authored_scope", sa.JSON(), nullable=False),
        sa.Column("resolved_scope", sa.JSON(), nullable=False),
        sa.Column(
            "listing_settings",
            sa.JSON(none_as_null=True),
            nullable=True,
        ),
        sa.Column(
            "detail_settings",
            sa.JSON(none_as_null=True),
            nullable=True,
        ),
        sa.Column("readiness", sa.JSON(), nullable=False),
        sa.Column("detail_target_count", sa.Integer(), nullable=False),
        sa.Column("plan_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confirmation_required", sa.Boolean(), nullable=False),
        sa.Column(
            "confirmation_token_hash",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column("prepared_by", sa.String(length=255), nullable=False),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crawl_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.CheckConstraint(
            "state IN ('prepared', 'consumed', 'expired')",
            name="ck_crawl_dispatch_plans_state",
        ),
        sa.CheckConstraint(
            "source_site IN ('jobsdb', 'ctgoodjobs', 'offertoday')",
            name="ck_crawl_dispatch_plans_source_site",
        ),
        sa.CheckConstraint(
            "crawl_phase IN ('listing', 'detail')",
            name="ck_crawl_dispatch_plans_crawl_phase",
        ),
        sa.CheckConstraint(
            "trigger_kind IN ('one_off', 'saved_automation', "
            "'scheduled_automation')",
            name="ck_crawl_dispatch_plans_trigger_kind",
        ),
        sa.CheckConstraint(
            "(trigger_kind = 'one_off' AND automation_id IS NULL "
            "AND automation_id_snapshot IS NULL "
            "AND expected_automation_revision IS NULL) OR "
            "(trigger_kind IN ('saved_automation', 'scheduled_automation') "
            "AND automation_id_snapshot IS NOT NULL "
            "AND expected_automation_revision > 0)",
            name="ck_crawl_dispatch_plans_automation_shape",
        ),
        sa.CheckConstraint(
            "(crawl_phase = 'listing' AND listing_settings IS NOT NULL "
            "AND detail_settings IS NULL AND detail_target_count = 0) OR "
            "(crawl_phase = 'detail' AND listing_settings IS NULL "
            "AND detail_settings IS NOT NULL AND detail_target_count >= 0)",
            name="ck_crawl_dispatch_plans_execution_settings",
        ),
        sa.CheckConstraint(
            "length(plan_fingerprint) = 64",
            name="ck_crawl_dispatch_plans_fingerprint",
        ),
        sa.CheckConstraint(
            "(confirmation_required AND confirmation_token_hash IS NOT NULL "
            "AND length(confirmation_token_hash) = 64) "
            "OR (NOT confirmation_required AND "
            "confirmation_token_hash IS NULL)",
            name="ck_crawl_dispatch_plans_confirmation_hash",
        ),
        sa.CheckConstraint(
            "expires_at > prepared_at",
            name="ck_crawl_dispatch_plans_expiry",
        ),
        sa.CheckConstraint(
            "(state = 'prepared' AND consumed_at IS NULL "
            "AND crawl_job_id IS NULL) OR "
            "(state = 'consumed' AND consumed_at IS NOT NULL "
            "AND crawl_job_id IS NOT NULL) OR "
            "(state = 'expired' AND consumed_at IS NULL "
            "AND crawl_job_id IS NULL)",
            name="ck_crawl_dispatch_plans_state_shape",
        ),
        sa.ForeignKeyConstraint(
            ["automation_id"],
            ["scrape_schedules.id"],
            name="fk_crawl_dispatch_plans_automation_id_scrape_schedules",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_revision_id", "source_site"],
            ["source_catalog_revisions.id", "source_catalog_revisions.source_site"],
            name="fk_crawl_dispatch_plans_catalog_revision_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_fingerprint",
            name="uq_crawl_dispatch_plans_fingerprint",
        ),
        sa.UniqueConstraint(
            "crawl_job_id",
            name="uq_crawl_dispatch_plans_crawl_job_id",
        ),
    )
    op.create_index(
        "ix_crawl_dispatch_plans_state",
        "crawl_dispatch_plans",
        ["state"],
    )
    op.create_index(
        "ix_crawl_dispatch_plans_source_site",
        "crawl_dispatch_plans",
        ["source_site"],
    )
    op.create_index(
        "ix_crawl_dispatch_plans_crawl_phase",
        "crawl_dispatch_plans",
        ["crawl_phase"],
    )
    op.create_index(
        "ix_crawl_dispatch_plans_automation_id",
        "crawl_dispatch_plans",
        ["automation_id"],
    )
    op.create_index(
        "ix_crawl_dispatch_plans_automation_id_snapshot",
        "crawl_dispatch_plans",
        ["automation_id_snapshot"],
    )
    op.create_index(
        "ix_crawl_dispatch_plans_catalog_revision_id",
        "crawl_dispatch_plans",
        ["catalog_revision_id"],
    )
    op.create_index(
        "ix_crawl_dispatch_plans_state_expiry",
        "crawl_dispatch_plans",
        ["state", "expires_at"],
    )
    op.create_index(
        "ix_crawl_dispatch_plans_automation_revision",
        "crawl_dispatch_plans",
        ["automation_id", "expected_automation_revision"],
    )

    op.create_table(
        "crawl_dispatch_plan_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_site", sa.String(length=32), nullable=False),
        sa.Column("source_job_id", sa.String(length=255), nullable=False),
        sa.Column("selection_order", sa.Integer(), nullable=False),
        sa.Column("eligibility_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("eligibility_status", sa.String(length=32), nullable=False),
        sa.Column("status_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "selection_order >= 0 AND length(eligibility_fingerprint) = 64",
            name="ck_crawl_dispatch_plan_targets_selection",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["crawl_dispatch_plans.id"],
            name="fk_crawl_dispatch_plan_targets_plan_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_id",
            "source_site",
            "source_job_id",
            name="uq_crawl_dispatch_plan_targets_identity",
        ),
        sa.UniqueConstraint(
            "plan_id",
            "selection_order",
            name="uq_crawl_dispatch_plan_targets_order",
        ),
    )
    op.create_index(
        "ix_crawl_dispatch_plan_targets_plan_id",
        "crawl_dispatch_plan_targets",
        ["plan_id"],
    )
    op.create_index(
        "ix_crawl_dispatch_plan_targets_source_job",
        "crawl_dispatch_plan_targets",
        ["source_site", "source_job_id"],
    )

    op.create_table(
        "crawl_dispatch_plan_target_rows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "crawl_job_listing_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("row_order", sa.Integer(), nullable=False),
        sa.Column("eligibility_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("eligibility_status", sa.String(length=32), nullable=False),
        sa.Column("status_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "row_order >= 0 AND length(eligibility_fingerprint) = 64",
            name="ck_crawl_dispatch_plan_target_rows_selection",
        ),
        sa.ForeignKeyConstraint(
            ["plan_target_id"],
            ["crawl_dispatch_plan_targets.id"],
            name="fk_crawl_dispatch_plan_target_rows_plan_target_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["crawl_job_listing_id"],
            ["crawl_job_listings.id"],
            name="fk_crawl_dispatch_plan_target_rows_listing_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "plan_target_id",
            "crawl_job_listing_id",
            name="uq_crawl_dispatch_plan_target_rows_membership",
        ),
        sa.UniqueConstraint(
            "plan_target_id",
            "row_order",
            name="uq_crawl_dispatch_plan_target_rows_order",
        ),
    )
    op.create_index(
        "ix_crawl_dispatch_plan_target_rows_plan_target_id",
        "crawl_dispatch_plan_target_rows",
        ["plan_target_id"],
    )
    op.create_index(
        "ix_crawl_dispatch_plan_target_rows_crawl_job_listing_id",
        "crawl_dispatch_plan_target_rows",
        ["crawl_job_listing_id"],
    )

    op.add_column(
        "crawl_jobs",
        sa.Column("dispatch_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "crawl_jobs",
        sa.Column("dispatch_plan_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "crawl_jobs",
        sa.Column("resume_context", sa.JSON(none_as_null=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_crawl_jobs_dispatch_plan_id_crawl_dispatch_plans",
        "crawl_jobs",
        "crawl_dispatch_plans",
        ["dispatch_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_crawl_jobs_dispatch_plan_id",
        "crawl_jobs",
        ["dispatch_plan_id"],
    )
    op.create_check_constraint(
        "ck_crawl_jobs_dispatch_plan_link",
        "crawl_jobs",
        "(dispatch_plan_id IS NULL AND dispatch_plan_fingerprint IS NULL) OR "
        "(dispatch_plan_id IS NOT NULL AND "
        "dispatch_plan_fingerprint IS NOT NULL AND "
        "length(dispatch_plan_fingerprint) = 64)",
    )
    op.create_index(
        "ix_crawl_jobs_dispatch_plan_id",
        "crawl_jobs",
        ["dispatch_plan_id"],
    )

    op.add_column(
        "schedule_executions",
        sa.Column("dispatch_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "schedule_executions",
        sa.Column("dispatch_plan_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_foreign_key(
        "fk_schedule_executions_dispatch_plan_id_crawl_dispatch_plans",
        "schedule_executions",
        "crawl_dispatch_plans",
        ["dispatch_plan_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_schedule_executions_dispatch_plan_id",
        "schedule_executions",
        ["dispatch_plan_id"],
    )
    op.create_check_constraint(
        "ck_schedule_executions_dispatch_plan_link",
        "schedule_executions",
        "(dispatch_plan_id IS NULL AND dispatch_plan_fingerprint IS NULL) OR "
        "(dispatch_plan_id IS NOT NULL AND "
        "dispatch_plan_fingerprint IS NOT NULL AND "
        "length(dispatch_plan_fingerprint) = 64)",
    )
    op.create_index(
        "ix_schedule_executions_dispatch_plan_id",
        "schedule_executions",
        ["dispatch_plan_id"],
    )

    op.create_foreign_key(
        "fk_crawl_dispatch_plans_crawl_job_id_crawl_jobs",
        "crawl_dispatch_plans",
        "crawl_jobs",
        ["crawl_job_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    _create_immutability_triggers()


def _create_immutability_triggers() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_crawl_dispatch_plan_immutability()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF OLD.state <> 'expired' THEN
              RAISE EXCEPTION
                'Only expired unconsumed Dispatch Plans may be deleted';
            END IF;
            RETURN OLD;
          END IF;

          IF pg_trigger_depth() > 1
             AND OLD.automation_id IS NOT NULL
             AND NEW.automation_id IS NULL
             AND (to_jsonb(NEW) - 'automation_id')
                 = (to_jsonb(OLD) - 'automation_id') THEN
            RETURN NEW;
          END IF;

          IF (to_jsonb(NEW) - ARRAY['state', 'consumed_at', 'crawl_job_id'])
             IS DISTINCT FROM
             (to_jsonb(OLD) - ARRAY['state', 'consumed_at', 'crawl_job_id']) THEN
            RAISE EXCEPTION 'Dispatch Plan reviewed content is immutable';
          END IF;
          IF OLD.state <> 'prepared'
             OR NEW.state NOT IN ('consumed', 'expired') THEN
            RAISE EXCEPTION 'Dispatch Plan lifecycle transition is invalid';
          END IF;
          IF NEW.state = 'consumed'
             AND (NEW.consumed_at IS NULL OR NEW.crawl_job_id IS NULL) THEN
            RAISE EXCEPTION
              'Consumed Dispatch Plan requires one Crawl Job and timestamp';
          END IF;
          IF NEW.state = 'expired'
             AND (NEW.consumed_at IS NOT NULL OR NEW.crawl_job_id IS NOT NULL) THEN
            RAISE EXCEPTION 'Expired Dispatch Plan cannot attach a Crawl Job';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_crawl_dispatch_plans_immutable
        BEFORE UPDATE OR DELETE ON crawl_dispatch_plans
        FOR EACH ROW EXECUTE FUNCTION enforce_crawl_dispatch_plan_immutability()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_dispatch_snapshot_member_mutation()
        RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND pg_trigger_depth() > 1 THEN
            RETURN OLD;
          END IF;
          RAISE EXCEPTION 'Dispatch Plan target membership is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in (
        "crawl_dispatch_plan_targets",
        "crawl_dispatch_plan_target_rows",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION reject_dispatch_snapshot_member_mutation()
            """
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_dispatch_authority_link_update()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'Dispatch Plan execution authority is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in ("crawl_jobs", "schedule_executions"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_dispatch_authority_immutable
            BEFORE UPDATE OF dispatch_plan_id, dispatch_plan_fingerprint
            ON {table_name}
            FOR EACH ROW
            WHEN (
              OLD.dispatch_plan_id IS DISTINCT FROM NEW.dispatch_plan_id
              OR OLD.dispatch_plan_fingerprint IS DISTINCT FROM
                 NEW.dispatch_plan_fingerprint
            )
            EXECUTE FUNCTION reject_dispatch_authority_link_update()
            """
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_versioned_crawl_job_payload_update()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION
            'Versioned Crawl Job compatibility request payload is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_crawl_jobs_versioned_payload_immutable
        BEFORE UPDATE OF request_payload ON crawl_jobs
        FOR EACH ROW
        WHEN (
          OLD.dispatch_plan_id IS NOT NULL
          AND to_jsonb(OLD.request_payload)
              IS DISTINCT FROM to_jsonb(NEW.request_payload)
        )
        EXECUTE FUNCTION reject_versioned_crawl_job_payload_update()
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_crawl_jobs_versioned_payload_immutable "
        "ON crawl_jobs"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS reject_versioned_crawl_job_payload_update()"
    )
    for table_name in ("schedule_executions", "crawl_jobs"):
        op.execute(
            f"DROP TRIGGER IF EXISTS "
            f"trg_{table_name}_dispatch_authority_immutable ON {table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS reject_dispatch_authority_link_update()")
    for table_name in (
        "crawl_dispatch_plan_target_rows",
        "crawl_dispatch_plan_targets",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS reject_dispatch_snapshot_member_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_crawl_dispatch_plans_immutable "
        "ON crawl_dispatch_plans"
    )
    op.execute("DROP FUNCTION IF EXISTS enforce_crawl_dispatch_plan_immutability()")

    op.drop_constraint(
        "fk_crawl_dispatch_plans_crawl_job_id_crawl_jobs",
        "crawl_dispatch_plans",
        type_="foreignkey",
    )

    op.drop_index(
        "ix_schedule_executions_dispatch_plan_id",
        table_name="schedule_executions",
    )
    op.drop_constraint(
        "ck_schedule_executions_dispatch_plan_link",
        "schedule_executions",
        type_="check",
    )
    op.drop_constraint(
        "uq_schedule_executions_dispatch_plan_id",
        "schedule_executions",
        type_="unique",
    )
    op.drop_constraint(
        "fk_schedule_executions_dispatch_plan_id_crawl_dispatch_plans",
        "schedule_executions",
        type_="foreignkey",
    )
    op.drop_column("schedule_executions", "dispatch_plan_fingerprint")
    op.drop_column("schedule_executions", "dispatch_plan_id")

    op.drop_index("ix_crawl_jobs_dispatch_plan_id", table_name="crawl_jobs")
    op.drop_constraint(
        "ck_crawl_jobs_dispatch_plan_link",
        "crawl_jobs",
        type_="check",
    )
    op.drop_constraint(
        "uq_crawl_jobs_dispatch_plan_id",
        "crawl_jobs",
        type_="unique",
    )
    op.drop_constraint(
        "fk_crawl_jobs_dispatch_plan_id_crawl_dispatch_plans",
        "crawl_jobs",
        type_="foreignkey",
    )
    op.drop_column("crawl_jobs", "dispatch_plan_fingerprint")
    op.drop_column("crawl_jobs", "dispatch_plan_id")
    op.drop_column("crawl_jobs", "resume_context")

    op.drop_table("crawl_dispatch_plan_target_rows")
    op.drop_table("crawl_dispatch_plan_targets")
    op.drop_table("crawl_dispatch_plans")
