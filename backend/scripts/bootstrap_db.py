#!/usr/bin/env python3
"""Bootstrap local database extensions and ORM tables."""
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Base, engine
import app.models  # noqa: F401  # Ensure all ORM models are registered on Base.metadata.


def bootstrap_database(*, db_engine=engine, metadata=Base.metadata) -> None:
    """Ensure required extensions exist before creating ORM tables."""
    with db_engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
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
                "UPDATE scrape_schedules "
                "SET crawl_mode = CASE "
                "WHEN COALESCE(NULLIF(source_site, ''), 'jobsdb') = 'jobsdb' THEN 'headed' "
                "WHEN COALESCE(NULLIF(source_site, ''), 'jobsdb') = 'ctgoodjobs' THEN 'headless' "
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

    metadata.create_all(bind=db_engine)


def main() -> None:
    """Run the local database bootstrap flow."""
    print("Ensuring database extensions...")
    print("Creating database tables...")
    bootstrap_database()
    print("✓ Database bootstrap completed successfully")


if __name__ == "__main__":
    main()
