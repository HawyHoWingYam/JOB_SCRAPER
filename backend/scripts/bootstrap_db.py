#!/usr/bin/env python3
"""Converge fresh or Alembic-managed databases to the repository head."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.schema import MetaData

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  # Register every ORM table on Base.metadata.


ALEMBIC_CONFIG_PATH = Path(__file__).resolve().parents[1] / "alembic.ini"
METADATA_BASE_REVISION = "20260720_180000"
TARGET_REVISION = "head"

MigrationRunner = Callable[[Engine, str, str], None]


class DatabaseBootstrapError(RuntimeError):
    """Raised when bootstrap cannot safely infer the database lineage."""


def _run_alembic(engine: Engine, action: str, revision: str) -> None:
    config = Config(str(ALEMBIC_CONFIG_PATH))
    rendered_url = engine.url.render_as_string(hide_password=False).replace("%", "%%")
    config.set_main_option("sqlalchemy.url", rendered_url)
    if action == "stamp":
        command.stamp(config, revision)
        return
    if action == "upgrade":
        command.upgrade(config, revision)
        return
    if action == "downgrade":
        command.downgrade(config, revision)
        return
    raise ValueError(f"Unsupported Alembic bootstrap action: {action}")


def _application_tables(db_engine: Engine) -> tuple[set[str], bool]:
    table_names = set(inspect(db_engine).get_table_names())
    has_version_table = "alembic_version" in table_names
    table_names.discard("alembic_version")
    return table_names, has_version_table


def _read_schema_revision(db_engine: Engine) -> str:
    with db_engine.connect() as connection:
        revisions = tuple(
            str(row[0]).strip()
            for row in connection.execute(
                text("SELECT version_num FROM alembic_version")
            )
            if str(row[0]).strip()
        )
    if len(revisions) != 1:
        raise DatabaseBootstrapError(
            "Alembic-managed database must contain exactly one schema revision"
        )
    return revisions[0]


def bootstrap_database(
    *,
    db_engine: Engine = engine,
    metadata: MetaData = Base.metadata,
    migration_runner: MigrationRunner | None = None,
) -> None:
    """Create a fresh metadata schema or upgrade an explicitly stamped schema.

    The historical Alembic base predates the repository's core tables. Fresh
    databases are therefore created from canonical ORM metadata, stamped at the
    last metadata-equivalent revision, and converged through the current head.
    A non-empty, unstamped database is ambiguous and fails closed.
    """

    runner = migration_runner or _run_alembic
    application_tables, has_version_table = _application_tables(db_engine)

    if application_tables and not has_version_table:
        raise DatabaseBootstrapError(
            "Refusing to bootstrap a non-empty database without alembic_version; "
            "stamp it only after an operator verifies its schema lineage"
        )
    if has_version_table and not application_tables:
        raise DatabaseBootstrapError(
            "Alembic revision exists but application tables are missing"
        )

    if application_tables:
        _read_schema_revision(db_engine)
        runner(db_engine, "upgrade", TARGET_REVISION)
        return

    if db_engine.dialect.name == "postgresql":
        with db_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    metadata.create_all(bind=db_engine)
    runner(db_engine, "stamp", METADATA_BASE_REVISION)
    runner(db_engine, "upgrade", TARGET_REVISION)


def main() -> None:
    """Run the local database bootstrap flow."""
    print("Converging database schema...")
    bootstrap_database()
    print("✓ Database bootstrap completed successfully")


if __name__ == "__main__":
    main()
