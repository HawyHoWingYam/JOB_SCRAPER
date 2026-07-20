from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
import pytest

from scripts.bootstrap_db import (
    DatabaseBootstrapError,
    METADATA_BASE_REVISION,
    bootstrap_database,
)


def _metadata() -> MetaData:
    metadata = MetaData()
    Table("bootstrap_probe", metadata, Column("id", Integer, primary_key=True))
    return metadata


def test_fresh_bootstrap_creates_metadata_then_stamps_and_upgrades() -> None:
    engine = create_engine("sqlite:///:memory:")
    actions: list[tuple[str, str]] = []

    bootstrap_database(
        db_engine=engine,
        metadata=_metadata(),
        migration_runner=lambda _engine, action, revision: actions.append(
            (action, revision)
        ),
    )

    assert "bootstrap_probe" in inspect(engine).get_table_names()
    assert actions == [("stamp", METADATA_BASE_REVISION), ("upgrade", "head")]


def test_stamped_database_uses_only_existing_db_convergence() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = _metadata()
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": METADATA_BASE_REVISION},
        )
    actions: list[tuple[str, str]] = []

    bootstrap_database(
        db_engine=engine,
        metadata=metadata,
        migration_runner=lambda _engine, action, revision: actions.append(
            (action, revision)
        ),
    )

    assert actions == [("upgrade", "head")]


def test_nonempty_unstamped_database_fails_closed() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = _metadata()
    metadata.create_all(engine)

    with pytest.raises(DatabaseBootstrapError, match="non-empty database"):
        bootstrap_database(
            db_engine=engine,
            metadata=metadata,
            migration_runner=lambda *_args: None,
        )


def test_stamped_database_without_application_tables_fails_closed() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": METADATA_BASE_REVISION},
        )

    with pytest.raises(DatabaseBootstrapError, match="application tables are missing"):
        bootstrap_database(
            db_engine=engine,
            metadata=_metadata(),
            migration_runner=lambda *_args: None,
        )
