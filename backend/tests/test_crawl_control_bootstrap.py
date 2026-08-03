from __future__ import annotations

import os

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, inspect, text
from sqlalchemy.engine import make_url

from scripts import bootstrap_db as bootstrap_module
from app.job_intelligence.source_attributes import (
    EMPLOYMENT_TYPE_SEEDS,
    EmploymentTypeRegistryError,
    reconcile_employment_type_registry,
)
from app.models.source_job_attributes import EmploymentType
from scripts.bootstrap_db import DatabaseBootstrapError, bootstrap_database
from scripts.repair_employment_type_registry import (
    EmploymentTypeRegistryRepairError,
    repair_employment_type_registry,
)


def _metadata() -> MetaData:
    metadata = MetaData()
    Table("bootstrap_probe", metadata, Column("id", Integer, primary_key=True))
    return metadata


def _registry_metadata() -> MetaData:
    metadata = MetaData()
    EmploymentType.__table__.to_metadata(metadata)
    return metadata


def test_empty_bootstrap_creates_only_current_metadata() -> None:
    engine = create_engine("sqlite:///:memory:")

    bootstrap_database(db_engine=engine, metadata=_metadata())

    assert inspect(engine).get_table_names() == ["bootstrap_probe"]


def test_empty_bootstrap_seeds_exact_employment_type_registry() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = _registry_metadata()

    bootstrap_database(db_engine=engine, metadata=metadata)

    table = metadata.tables["employment_types"]
    with engine.connect() as connection:
        rows = connection.execute(
            table.select().order_by(table.c.sort_order)
        ).tuples().all()
    assert rows == list(EMPLOYMENT_TYPE_SEEDS)


def test_registry_repair_inserts_updates_and_preserves_unknown_codes() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = _registry_metadata()
    bootstrap_database(db_engine=engine, metadata=metadata)
    table = metadata.tables["employment_types"]
    with engine.begin() as connection:
        connection.execute(table.delete().where(table.c.code == "part_time"))
        connection.execute(
            table.update()
            .where(table.c.code == "full_time")
            .values(label="Full time legacy", sort_order=20)
        )
        connection.execute(
            table.insert(),
            {"code": "seasonal", "label": "Seasonal", "sort_order": 99},
        )

    repaired = repair_employment_type_registry(db_engine=engine)
    rerun = repair_employment_type_registry(db_engine=engine)

    assert repaired.inserted_codes == ("part_time",)
    assert repaired.updated_codes == ("full_time",)
    assert repaired.unknown_codes == ("seasonal",)
    assert rerun.inserted_codes == ()
    assert rerun.updated_codes == ()
    assert rerun.unchanged_codes == tuple(
        code for code, _label, _sort_order in EMPLOYMENT_TYPE_SEEDS
    )
    assert rerun.unknown_codes == ("seasonal",)
    with engine.connect() as connection:
        canonical_rows = connection.execute(
            table.select()
            .where(table.c.code != "seasonal")
            .order_by(table.c.sort_order)
        ).tuples().all()
        unknown_row = connection.execute(
            table.select().where(table.c.code == "seasonal")
        ).tuples().one()
    assert canonical_rows == list(EMPLOYMENT_TYPE_SEEDS)
    assert unknown_row == ("seasonal", "Seasonal", 99)


def test_registry_repair_canonicalizes_swapped_unique_values() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = _registry_metadata()
    bootstrap_database(db_engine=engine, metadata=metadata)
    table = metadata.tables["employment_types"]
    with engine.begin() as connection:
        connection.execute(
            table.update()
            .where(table.c.code == "full_time")
            .values(label="Temporary Full Time", sort_order=20)
        )
        connection.execute(
            table.update()
            .where(table.c.code == "part_time")
            .values(label="Full-time", sort_order=1)
        )
        connection.execute(
            table.update()
            .where(table.c.code == "full_time")
            .values(label="Part-time", sort_order=2)
        )

    result = repair_employment_type_registry(db_engine=engine)

    assert result.updated_codes == ("full_time", "part_time")
    with engine.connect() as connection:
        rows = connection.execute(
            table.select().order_by(table.c.sort_order)
        ).tuples().all()
    assert rows == list(EMPLOYMENT_TYPE_SEEDS)


def test_registry_repair_refuses_unknown_row_occupying_canonical_value() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = _registry_metadata()
    metadata.create_all(engine)
    table = metadata.tables["employment_types"]
    with engine.begin() as connection:
        connection.execute(
            table.insert(),
            {"code": "unknown", "label": "Full-time", "sort_order": 1},
        )

    with engine.begin() as connection:
        with pytest.raises(EmploymentTypeRegistryError, match="occupy canonical"):
            reconcile_employment_type_registry(connection)


def test_registry_repair_requires_existing_table_without_schema_mutation() -> None:
    engine = create_engine("sqlite:///:memory:")

    with pytest.raises(EmploymentTypeRegistryRepairError, match="existing"):
        repair_employment_type_registry(db_engine=engine)

    assert inspect(engine).get_table_names() == []


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
    metadata = _registry_metadata()
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        bootstrap_database(db_engine=engine, metadata=metadata)
        assert set(inspect(engine).get_table_names()) == set(metadata.tables)
        assert "alembic_version" not in inspect(engine).get_table_names()
        table = metadata.tables["employment_types"]
        with engine.connect() as connection:
            rows = connection.execute(
                table.select().order_by(table.c.sort_order)
            ).tuples().all()
        assert rows == list(EMPLOYMENT_TYPE_SEEDS)
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()


def test_disposable_postgres_bootstrap_rolls_back_schema_when_seed_fails(
    monkeypatch,
) -> None:
    database_url = os.getenv("SCHEMA_BOOTSTRAP_POSTGRES_TEST_URL", "").strip()
    if not database_url:
        pytest.skip("SCHEMA_BOOTSTRAP_POSTGRES_TEST_URL is not configured")
    database_name = make_url(database_url).database
    if database_name is None or not database_name.endswith("_test"):
        raise RuntimeError(
            "SCHEMA_BOOTSTRAP_POSTGRES_TEST_URL database name must end in _test"
        )

    engine = create_engine(database_url, pool_pre_ping=True)
    metadata = _registry_metadata()
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))

        def fail_registry_seed(*_args, **_kwargs):
            raise RuntimeError("forced registry seed failure")

        monkeypatch.setattr(
            bootstrap_module,
            "reconcile_employment_type_registry",
            fail_registry_seed,
        )
        with pytest.raises(RuntimeError, match="forced registry seed failure"):
            bootstrap_database(db_engine=engine, metadata=metadata)

        assert inspect(engine).get_table_names() == []
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()
