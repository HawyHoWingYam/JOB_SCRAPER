from __future__ import annotations

from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

import pytest


def test_source_catalog_governance_migration_is_destructive_and_explicit(monkeypatch):
    dropped_tables: list[str] = []
    dropped_columns: list[str] = []
    executed_sql: list[str] = []

    alembic_stub = ModuleType("alembic")
    alembic_stub.op = SimpleNamespace(
        drop_constraint=lambda *_args, **_kwargs: None,
        drop_index=lambda *_args, **_kwargs: None,
        drop_column=lambda _table, column: dropped_columns.append(column),
        create_check_constraint=lambda *_args, **_kwargs: None,
        drop_table=lambda name: dropped_tables.append(name),
        execute=lambda statement: executed_sql.append(str(statement)),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)

    migration = runpy.run_path(
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260726_180000_drop_source_catalog_governance.py"
    )
    migration["upgrade"]()

    assert migration["revision"] == "20260726_180000"
    assert migration["down_revision"] == "20260726_160000"
    assert dropped_columns == [
        "source_catalog_fingerprint",
        "source_catalog_sequence",
        "source_catalog_revision_id",
    ]
    assert dropped_tables == [
        "source_catalog_publications",
        "source_catalog_change_reviews",
        "source_catalog_active_revisions",
        "source_catalog_revisions",
        "source_catalog_validation_runs",
        "source_catalog_candidates",
    ]
    assert all("DROP FUNCTION" in statement for statement in executed_sql)
    with pytest.raises(RuntimeError, match="intentional sandbox cutover"):
        migration["downgrade"]()
