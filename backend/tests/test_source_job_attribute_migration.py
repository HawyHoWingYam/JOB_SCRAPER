from __future__ import annotations

from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace


def test_source_job_attribute_migration_is_additive_and_seeds_only_governed_types(
    monkeypatch,
):
    created_tables: list[str] = []
    dropped_tables: list[str] = []
    seeded_rows: list[dict[str, object]] = []
    created_constraints: list[tuple[str, str]] = []

    def create_table(name, *_columns, **_kwargs):
        created_tables.append(name)
        return SimpleNamespace(name=name)

    alembic_stub = ModuleType("alembic")
    alembic_stub.op = SimpleNamespace(
        create_table=create_table,
        create_index=lambda *_args, **_kwargs: None,
        create_unique_constraint=lambda name, table, *_columns: (
            created_constraints.append((name, table))
        ),
        bulk_insert=lambda table, rows: seeded_rows.extend(rows),
        drop_index=lambda *_args, **_kwargs: None,
        drop_constraint=lambda *_args, **_kwargs: None,
        drop_table=lambda name: dropped_tables.append(name),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)

    migration = runpy.run_path(
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260718_220000_add_source_job_attributes.py"
    )
    migration["upgrade"]()
    migration["downgrade"]()

    assert {
        "revision": migration["revision"],
        "down_revision": migration["down_revision"],
        "created_tables": created_tables,
        "dropped_tables": dropped_tables,
        "catalog_constraint": created_constraints,
        "seeded_rows": seeded_rows,
    } == {
        "revision": "20260718_220000",
        "down_revision": "20260718_210000",
        "created_tables": [
            "job_source_attribute_projections",
            "employment_types",
            "job_source_classification_paths",
            "job_source_classification_path_nodes",
            "job_source_employment_labels",
            "job_employment_types",
        ],
        "dropped_tables": list(reversed(created_tables)),
        "catalog_constraint": [
            (
                "uq_source_catalog_revision_id_source",
                "source_catalog_revisions",
            )
        ],
        "seeded_rows": [
            {"code": "full_time", "label": "Full-time", "sort_order": 1},
            {"code": "part_time", "label": "Part-time", "sort_order": 2},
            {"code": "permanent", "label": "Permanent", "sort_order": 3},
            {"code": "contract", "label": "Contract", "sort_order": 4},
            {"code": "temporary", "label": "Temporary", "sort_order": 5},
            {"code": "internship", "label": "Internship", "sort_order": 6},
            {"code": "freelance", "label": "Freelance", "sort_order": 7},
        ],
    }
