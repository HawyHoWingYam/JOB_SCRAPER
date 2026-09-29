"""Idempotently install the PostgreSQL indexes used by Job Browser search."""

from sqlalchemy import text

from app.database import engine


INDEX_STATEMENTS = (
    "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    "CREATE INDEX IF NOT EXISTS ix_jobs_description_trgm "
    "ON jobs USING gin (description gin_trgm_ops)",
)


def upgrade_job_search_indexes() -> None:
    with engine.begin() as connection:
        for statement in INDEX_STATEMENTS:
            connection.execute(text(statement))


if __name__ == "__main__":
    upgrade_job_search_indexes()
    print("Job Browser search indexes are current.")
