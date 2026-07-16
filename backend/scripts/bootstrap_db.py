#!/usr/bin/env python3
"""Bootstrap local database extensions and ORM tables."""
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Base, engine
import app.models  # noqa: F401  # Ensure all ORM models are registered on Base.metadata.


def bootstrap_database(*, db_engine=engine, metadata=Base.metadata) -> None:
    """Ensure required extensions exist, then create tables, then run migrations."""
    with db_engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    # Create all ORM tables first (fresh DB needs the base tables)
    metadata.create_all(bind=db_engine)

    # Then run migration ALTER TABLE / UPDATE statements for existing DBs
    with db_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO scraper_pacing_settings ("
                "source_site, interval_min_seconds, interval_max_seconds, "
                "burst_size, burst_pause_seconds, updated_at"
                ") VALUES "
                "('jobsdb', 1, 3, 20, 30, CURRENT_TIMESTAMP), "
                "('ctgoodjobs', 1, 3, 20, 30, CURRENT_TIMESTAMP), "
                "('offertoday', 1, 3, 20, 30, CURRENT_TIMESTAMP) "
                "ON CONFLICT (source_site) DO NOTHING"
            )
        )
        connection.execute(text("ALTER TABLE scrape_schedules ADD COLUMN IF NOT EXISTS crawl_mode VARCHAR(32)"))
        connection.execute(text("ALTER TABLE scrape_schedules ADD COLUMN IF NOT EXISTS crawl_phase VARCHAR(32)"))
        connection.execute(text("ALTER TABLE scrape_schedules ADD COLUMN IF NOT EXISTS detail_limit INTEGER"))
        connection.execute(
            text("ALTER TABLE schedule_executions ADD COLUMN IF NOT EXISTS request_payload_snapshot JSON")
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_crawl_job_listings_source_status_rank_created "
                "ON crawl_job_listings (source_site, detail_status, listing_rank, created_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_crawl_job_listings_job_status "
                "ON crawl_job_listings (crawl_job_id, detail_status)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_crawl_job_listings_source_job_created "
                "ON crawl_job_listings (source_site, crawl_job_id, created_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_crawl_job_events_job_event_sequence "
                "ON crawl_job_events (crawl_job_id, event_type, sequence_no)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_crawl_jobs_status_queued_created "
                "ON crawl_jobs (status, queued_at, created_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_crawl_jobs_queued_created "
                "ON crawl_jobs (queued_at, created_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_executions_schedule_started "
                "ON schedule_executions (schedule_id, started_at)"
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_schedule_executions_crawl_job_started_created "
                "ON schedule_executions (crawl_job_id, started_at, created_at)"
            )
        )
        connection.execute(
            text(
                "UPDATE scrape_schedules "
                "SET crawl_mode = CASE "
                "WHEN COALESCE(NULLIF(source_site, ''), 'jobsdb') = 'jobsdb' THEN 'headed' "
                "WHEN COALESCE(NULLIF(source_site, ''), 'jobsdb') = 'ctgoodjobs' THEN 'headed' "
                "ELSE 'headless' END "
                "WHERE crawl_mode IS NULL"
            )
        )
        connection.execute(text("UPDATE scrape_schedules SET crawl_phase = 'listing' WHERE crawl_phase IS NULL"))
        connection.execute(text("UPDATE scrape_schedules SET detail_limit = 100 WHERE detail_limit IS NULL"))
        connection.execute(
            text(
                "UPDATE schedule_executions AS executions "
                "SET request_payload_snapshot = crawl_jobs.request_payload "
                "FROM crawl_jobs "
                "WHERE executions.crawl_job_id = crawl_jobs.id "
                "AND executions.request_payload_snapshot IS NULL "
                "AND crawl_jobs.request_payload IS NOT NULL"
            )
        )


def main() -> None:
    """Run the local database bootstrap flow."""
    print("Ensuring database extensions...")
    print("Creating database tables...")
    bootstrap_database()
    print("✓ Database bootstrap completed successfully")


if __name__ == "__main__":
    main()
