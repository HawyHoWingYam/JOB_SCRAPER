from __future__ import annotations

from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace


def test_cutover_convergence_migration_installs_maintenance_guards(monkeypatch) -> None:
    executed_sql: list[str] = []
    alembic_stub = ModuleType("alembic")
    setattr(
        alembic_stub,
        "op",
        SimpleNamespace(
        execute=lambda statement: executed_sql.append(str(statement))
        ),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)

    migration = runpy.run_path(
        str(
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260720_210000_converge_crawl_control_cutover.py"
        )
    )
    migration["upgrade"]()

    combined = "\n".join(executed_sql).upper()
    assert migration["down_revision"] == "20260720_180000"
    assert "CRAWL_CONTROL_MAINTENANCE_ENABLED" in combined
    assert "CURRENT_SETTING('APP.CRAWL_CONTROL_MAINTENANCE'" in combined
    assert "FK_CRAWL_JOB_LISTINGS_CRAWL_JOB_ID_CRAWL_JOBS" in combined
    assert "TRG_SOURCE_CATALOG_REVISIONS_IMMUTABLE" in combined
    assert "TRG_AUTOMATION_REVISIONS_IMMUTABLE" in combined
    assert "BEFORE UPDATE OR DELETE ON AUTOMATION_REVISIONS" in combined
    assert "TRG_CRAWL_DISPATCH_PLANS_IMMUTABLE" in combined
    assert "TRG_CRAWL_JOBS_DISPATCH_AUTHORITY_IMMUTABLE" in combined
    assert "TRG_CRAWL_JOBS_VERSIONED_PAYLOAD_IMMUTABLE" in combined
    assert "INSERT INTO" not in combined
