import runpy
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


def test_migration_seeds_three_sources_and_downgrades(monkeypatch):
    captured = {}

    def create_table(name, *columns):
        captured["table_name"] = name
        captured["columns"] = columns
        return object()

    alembic_stub = ModuleType("alembic")
    alembic_stub.op = SimpleNamespace(
        create_table=create_table,
        bulk_insert=lambda table, rows: captured.update(table=table, rows=rows),
        drop_table=lambda name: captured.update(dropped=name),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)
    migration = runpy.run_path(
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260716_180000_add_scraper_pacing_settings.py"
    )

    migration["upgrade"]()
    migration["downgrade"]()

    assert captured["table_name"] == "scraper_pacing_settings"
    assert [row["source_site"] for row in captured["rows"]] == [
        "jobsdb",
        "ctgoodjobs",
        "offertoday",
    ]
    assert all(
        row["interval_min_seconds"] == 1
        and row["interval_max_seconds"] == 3
        and row["burst_size"] == 20
        and row["burst_pause_seconds"] == 30
        for row in captured["rows"]
    )
    assert captured["dropped"] == "scraper_pacing_settings"
