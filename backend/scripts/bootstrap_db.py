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
        connection.execute(
            text(
                "UPDATE scrape_schedules "
                "SET crawl_mode = CASE "
                "WHEN COALESCE(NULLIF(source_site, ''), 'jobsdb') IN ('jobsdb', 'ctgoodjobs') THEN 'headed' "
                "ELSE 'headless' END "
                "WHERE crawl_mode IS NULL"
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
