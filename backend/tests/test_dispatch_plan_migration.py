from __future__ import annotations

from pathlib import Path
import runpy
import sys
from types import ModuleType, SimpleNamespace

from app.database import Base
from app.models.crawl_dispatch_plan import CRAWL_DISPATCH_PLAN_TABLES
from app.models.crawl_job import CrawlJob
from app.models.schedule import ScheduleExecution


def test_dispatch_plan_migration_is_schema_only_and_breaks_the_fk_cycle(
    monkeypatch,
):
    created_tables: list[str] = []
    dropped_tables: list[str] = []
    added_columns: list[tuple[str, str]] = []
    foreign_keys: list[tuple[str, str, str | None]] = []
    executed_sql: list[str] = []

    alembic_stub = ModuleType("alembic")
    alembic_stub.op = SimpleNamespace(
        add_column=lambda table, column: added_columns.append((table, column.name)),
        create_check_constraint=lambda *_args, **_kwargs: None,
        create_foreign_key=lambda name, source, *_args, **kwargs: (
            foreign_keys.append((name, source, kwargs.get("ondelete")))
        ),
        create_index=lambda *_args, **_kwargs: None,
        create_table=lambda name, *_columns, **_kwargs: created_tables.append(name),
        create_unique_constraint=lambda *_args, **_kwargs: None,
        drop_column=lambda *_args, **_kwargs: None,
        drop_constraint=lambda *_args, **_kwargs: None,
        drop_index=lambda *_args, **_kwargs: None,
        drop_table=lambda name: dropped_tables.append(name),
        execute=lambda statement: executed_sql.append(str(statement)),
    )
    monkeypatch.setitem(sys.modules, "alembic", alembic_stub)

    migration = runpy.run_path(
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260720_180000_add_crawl_dispatch_plans.py"
    )
    migration["upgrade"]()
    migration["downgrade"]()

    assert migration["down_revision"] == "20260720_120000"
    assert created_tables == [
        "crawl_dispatch_plans",
        "crawl_dispatch_plan_targets",
        "crawl_dispatch_plan_target_rows",
    ]
    assert dropped_tables == list(reversed(created_tables))
    assert {
        ("crawl_jobs", "dispatch_plan_id"),
        ("crawl_jobs", "dispatch_plan_fingerprint"),
        ("crawl_jobs", "resume_context"),
        ("schedule_executions", "dispatch_plan_id"),
        ("schedule_executions", "dispatch_plan_fingerprint"),
    } <= set(added_columns)
    assert (
        "fk_crawl_dispatch_plans_crawl_job_id_crawl_jobs",
        "crawl_dispatch_plans",
        "RESTRICT",
    ) in foreign_keys
    assert (
        "fk_crawl_jobs_dispatch_plan_id_crawl_dispatch_plans",
        "crawl_jobs",
        "RESTRICT",
    ) in foreign_keys
    assert not any("INSERT" in statement.upper() for statement in executed_sql)
    assert any(
        "TRG_CRAWL_DISPATCH_PLANS_IMMUTABLE" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "REJECT_DISPATCH_AUTHORITY_LINK_UPDATE" in statement.upper()
        for statement in executed_sql
    )
    assert any(
        "TRG_CRAWL_JOBS_VERSIONED_PAYLOAD_IMMUTABLE" in statement.upper()
        for statement in executed_sql
    )


def test_dispatch_plan_orm_metadata_registers_links_constraints_and_tables():
    assert {table.name for table in CRAWL_DISPATCH_PLAN_TABLES} <= set(
        Base.metadata.tables
    )
    assert {
        "dispatch_plan_id",
        "dispatch_plan_fingerprint",
        "resume_context",
    } <= set(CrawlJob.__table__.columns.keys())
    assert {
        "dispatch_plan_id",
        "dispatch_plan_fingerprint",
    } <= set(ScheduleExecution.__table__.columns.keys())

    job_plan_fk = next(iter(CrawlJob.__table__.c.dispatch_plan_id.foreign_keys))
    execution_plan_fk = next(
        iter(ScheduleExecution.__table__.c.dispatch_plan_id.foreign_keys)
    )
    plan_job_fk = next(
        iter(
            Base.metadata.tables["crawl_dispatch_plans"]
            .c.crawl_job_id.foreign_keys
        )
    )
    assert job_plan_fk.ondelete == "RESTRICT"
    assert execution_plan_fk.ondelete == "RESTRICT"
    assert plan_job_fk.ondelete == "RESTRICT"
    assert plan_job_fk.use_alter is True
