from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_source_catalog_migration_creates_schema_without_publishing_data(monkeypatch):
    created_tables: list[str] = []
    dropped_tables: list[str] = []
    executed_sql: list[str] = []

    alembic_stub = ModuleType("alembic")
    alembic_stub.op = SimpleNamespace(
        create_table=lambda name, *_columns, **_kwargs: created_tables.append(name),
        create_index=lambda *_args, **_kwargs: None,
        drop_index=lambda *_args, **_kwargs: None,
        drop_table=lambda name: dropped_tables.append(name),
        execute=lambda statement: executed_sql.append(str(statement)),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)

    migration = runpy.run_path(
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260718_180000_add_source_catalog_runtime.py"
    )
    migration["upgrade"]()
    migration["downgrade"]()

    assert created_tables == [
        "source_catalog_candidates",
        "source_catalog_validation_runs",
        "source_catalog_revisions",
        "source_catalog_active_revisions",
        "source_catalog_change_reviews",
        "source_catalog_publications",
    ]
    assert dropped_tables == list(reversed(created_tables))
    assert not any("INSERT" in statement.upper() for statement in executed_sql)
    assert any("TRG_SOURCE_CATALOG_REVISIONS_IMMUTABLE" in statement.upper() for statement in executed_sql)
    assert any("TRG_SOURCE_CATALOG_CANDIDATES_PAYLOAD_IMMUTABLE" in statement.upper() for statement in executed_sql)
