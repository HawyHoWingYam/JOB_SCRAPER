#!/usr/bin/env python3
"""Create the current application schema in an empty database."""

from __future__ import annotations

from pathlib import Path
import sys

from sqlalchemy import Connection, Engine, inspect, text
from sqlalchemy.schema import MetaData

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  # Register every ORM table on Base.metadata.
from app.job_intelligence.source_attributes import (  # noqa: E402
    reconcile_employment_type_registry,
)


class DatabaseBootstrapError(RuntimeError):
    """Raised when the target database is not safe for empty-schema bootstrap."""


def _lock_bootstrap(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.execute(
            text("SELECT pg_advisory_xact_lock(72639451028411732)")
        )


def _table_names(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def bootstrap_database(
    *,
    db_engine: Engine = engine,
    metadata: MetaData = Base.metadata,
) -> None:
    """Create exactly the current schema and refuse every non-empty database."""

    with db_engine.begin() as connection:
        _lock_bootstrap(connection)
        existing_tables = _table_names(connection)
        if existing_tables:
            rendered = ", ".join(sorted(existing_tables))
            raise DatabaseBootstrapError(
                "Refusing to bootstrap a non-empty database; clear the sandbox "
                f"schema first (found: {rendered})"
            )

        if connection.dialect.name == "postgresql":
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

        metadata.create_all(bind=connection)
        created_tables = _table_names(connection)
        expected_tables = {table.name for table in metadata.tables.values()}
        if created_tables != expected_tables:
            missing = ", ".join(sorted(expected_tables - created_tables)) or "none"
            unexpected = ", ".join(sorted(created_tables - expected_tables)) or "none"
            raise DatabaseBootstrapError(
                "Current schema bootstrap did not converge exactly "
                f"(missing: {missing}; unexpected: {unexpected})"
            )
        if "employment_types" in expected_tables:
            reconcile_employment_type_registry(
                connection,
                allow_unknown_codes=False,
            )


def main() -> None:
    print("Creating current schema in an empty database...")
    bootstrap_database()
    print("✓ Current schema bootstrap completed successfully")


if __name__ == "__main__":
    main()
