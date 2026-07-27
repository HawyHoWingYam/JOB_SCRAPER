from __future__ import annotations

import os

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import make_url

from scripts.bootstrap_db import DatabaseBootstrapError, bootstrap_database


def _metadata() -> MetaData:
    metadata = MetaData()
    Table("bootstrap_probe", metadata, Column("id", Integer, primary_key=True))
    return metadata


def test_empty_bootstrap_creates_only_current_metadata() -> None:
    engine = create_engine("sqlite:///:memory:")

    bootstrap_database(db_engine=engine, metadata=_metadata())

    assert inspect(engine).get_table_names() == ["bootstrap_probe"]


@pytest.mark.parametrize("table_name", ["bootstrap_probe", "alembic_version"])
def test_nonempty_database_fails_without_mutation(table_name: str) -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text(f'CREATE TABLE "{table_name}" (id INTEGER)'))
    before = inspect(engine).get_table_names()

    with pytest.raises(DatabaseBootstrapError, match="non-empty database"):
        bootstrap_database(db_engine=engine, metadata=_metadata())

    assert inspect(engine).get_table_names() == before


def test_disposable_postgres_bootstrap_creates_current_schema() -> None:
    database_url = os.getenv("SCHEMA_BOOTSTRAP_POSTGRES_TEST_URL", "").strip()
    if not database_url:
        pytest.skip("SCHEMA_BOOTSTRAP_POSTGRES_TEST_URL is not configured")
    database_name = make_url(database_url).database
    if database_name is None or not database_name.endswith("_test"):
        raise RuntimeError(
            "SCHEMA_BOOTSTRAP_POSTGRES_TEST_URL database name must end in _test"
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    metadata = _metadata()
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        bootstrap_database(db_engine=engine, metadata=metadata)
        assert set(inspect(engine).get_table_names()) == set(metadata.tables)
        assert "alembic_version" not in inspect(engine).get_table_names()
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()
