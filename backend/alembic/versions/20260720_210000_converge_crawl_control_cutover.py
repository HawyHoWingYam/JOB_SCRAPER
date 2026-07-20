"""converge Crawl Control bootstrap and maintenance guards

Revision ID: 20260720_210000
Revises: 20260720_180000
Create Date: 2026-07-20 21:00:00.000000
"""

from alembic import op


revision = "20260720_210000"
down_revision = "20260720_180000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Converge metadata-created and migrated databases at one guarded head."""
    _ensure_listing_crawl_job_foreign_key()
    _install_maintenance_setting()
    _install_source_catalog_guards()
    _install_automation_guards(maintenance_aware=True)
    _install_dispatch_plan_guards(maintenance_aware=True)


def downgrade() -> None:
    """Restore the pre-cutover trigger behavior while retaining prior guards."""
    _install_automation_guards(maintenance_aware=False)
    _install_dispatch_plan_guards(maintenance_aware=False)
    op.execute("DROP FUNCTION IF EXISTS crawl_control_maintenance_enabled()")


def _ensure_listing_crawl_job_foreign_key() -> None:
    # The historical migration installed this FK, while the ORM relationship is
    # intentionally view-only.  Fresh metadata therefore needs convergence.
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1
            FROM pg_constraint AS constraint_row
            JOIN pg_class AS source_table
              ON source_table.oid = constraint_row.conrelid
            JOIN pg_class AS target_table
              ON target_table.oid = constraint_row.confrelid
            JOIN pg_attribute AS source_column
              ON source_column.attrelid = source_table.oid
             AND source_column.attnum = ANY(constraint_row.conkey)
            WHERE constraint_row.contype = 'f'
              AND source_table.relname = 'crawl_job_listings'
              AND source_column.attname = 'crawl_job_id'
              AND target_table.relname = 'crawl_jobs'
          ) THEN
            ALTER TABLE crawl_job_listings
              ADD CONSTRAINT fk_crawl_job_listings_crawl_job_id_crawl_jobs
              FOREIGN KEY (crawl_job_id) REFERENCES crawl_jobs(id)
              ON DELETE CASCADE;
          END IF;
        END $$
        """
    )


def _install_maintenance_setting() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION crawl_control_maintenance_enabled()
        RETURNS boolean AS $$
        BEGIN
          RETURN COALESCE(
            current_setting('app.crawl_control_maintenance', true),
            ''
          ) = 'on';
        END;
        $$ LANGUAGE plpgsql STABLE
        """
    )


def _install_source_catalog_guards() -> None:
    # create_all cannot express PostgreSQL triggers. Reinstalling them here is
    # harmless for migrated databases and supplies them to metadata bootstraps.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_source_catalog_revision_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'source catalog revisions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_source_catalog_revisions_immutable "
        "ON source_catalog_revisions"
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
        CREATE OR REPLACE FUNCTION reject_source_catalog_candidate_payload_mutation()
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
        "DROP TRIGGER IF EXISTS trg_source_catalog_candidates_payload_immutable "
        "ON source_catalog_candidates"
    )
    op.execute(
        """
        CREATE TRIGGER trg_source_catalog_candidates_payload_immutable
        BEFORE UPDATE ON source_catalog_candidates
        FOR EACH ROW
        EXECUTE FUNCTION reject_source_catalog_candidate_payload_mutation()
        """
    )


def _install_automation_guards(*, maintenance_aware: bool) -> None:
    maintenance_clause = """
          IF crawl_control_maintenance_enabled() THEN
            IF TG_OP = 'DELETE' THEN
              RETURN OLD;
            END IF;
            RETURN NEW;
          END IF;
    """ if maintenance_aware else ""
    trigger_operations = "UPDATE OR DELETE" if maintenance_aware else "UPDATE"
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION reject_automation_revision_update()
        RETURNS trigger AS $$
        BEGIN
{maintenance_clause}
          RAISE EXCEPTION 'Automation revisions are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_automation_revisions_immutable "
        "ON automation_revisions"
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_automation_revisions_immutable
        BEFORE {trigger_operations} ON automation_revisions
        FOR EACH ROW EXECUTE FUNCTION reject_automation_revision_update()
        """
    )


def _install_dispatch_plan_guards(*, maintenance_aware: bool) -> None:
    plan_maintenance_clause = """
          IF crawl_control_maintenance_enabled() THEN
            IF TG_OP = 'DELETE' THEN
              RETURN OLD;
            END IF;
            RETURN NEW;
          END IF;
    """ if maintenance_aware else ""
    member_maintenance_clause = """
          IF crawl_control_maintenance_enabled() THEN
            IF TG_OP = 'DELETE' THEN
              RETURN OLD;
            END IF;
            RETURN NEW;
          END IF;
    """ if maintenance_aware else ""
    authority_maintenance_clause = """
          IF crawl_control_maintenance_enabled() THEN
            RETURN NEW;
          END IF;
    """ if maintenance_aware else ""

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION enforce_crawl_dispatch_plan_immutability()
        RETURNS trigger AS $$
        BEGIN
{plan_maintenance_clause}
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
        "DROP TRIGGER IF EXISTS trg_crawl_dispatch_plans_immutable "
        "ON crawl_dispatch_plans"
    )
    op.execute(
        """
        CREATE TRIGGER trg_crawl_dispatch_plans_immutable
        BEFORE UPDATE OR DELETE ON crawl_dispatch_plans
        FOR EACH ROW EXECUTE FUNCTION enforce_crawl_dispatch_plan_immutability()
        """
    )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION reject_dispatch_snapshot_member_mutation()
        RETURNS trigger AS $$
        BEGIN
{member_maintenance_clause}
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
            f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}"
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_immutable
            BEFORE UPDATE OR DELETE ON {table_name}
            FOR EACH ROW
            EXECUTE FUNCTION reject_dispatch_snapshot_member_mutation()
            """
        )

    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION reject_dispatch_authority_link_update()
        RETURNS trigger AS $$
        BEGIN
{authority_maintenance_clause}
          RAISE EXCEPTION 'Dispatch Plan execution authority is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in ("crawl_jobs", "schedule_executions"):
        op.execute(
            f"DROP TRIGGER IF EXISTS "
            f"trg_{table_name}_dispatch_authority_immutable ON {table_name}"
        )
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
        f"""
        CREATE OR REPLACE FUNCTION reject_versioned_crawl_job_payload_update()
        RETURNS trigger AS $$
        BEGIN
{authority_maintenance_clause}
          RAISE EXCEPTION
            'Versioned Crawl Job compatibility request payload is immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_crawl_jobs_versioned_payload_immutable "
        "ON crawl_jobs"
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
