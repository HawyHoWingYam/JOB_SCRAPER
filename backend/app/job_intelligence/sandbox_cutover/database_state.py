from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, MetaData, func, inspect, select, text


RUNTIME_TABLE_NAMES = (
    "automation_delete_reviews",
    "classification_batch_run_items",
    "classification_batch_runs",
    "company_enrichment_run_items",
    "company_enrichment_runs",
    "crawl_dispatch_plan_target_rows",
    "crawl_dispatch_plan_targets",
    "crawl_dispatch_plans",
    "crawl_job_events",
    "crawl_job_executions",
    "crawl_job_listings",
    "crawl_jobs",
    "crawl_runs",
    "enrichment_run_items",
    "enrichment_runs",
    "event_outbox",
    "schedule_executions",
    "scheduler_runtime_heartbeats",
    "scrape_schedules",
)

FORBIDDEN_TABLE_NAMES = (
    "governance_revisions",
    "canonical_job_taxonomy_releases",
    "canonical_job_taxonomy_active_revisions",
    "canonical_job_taxonomy_mapping_revisions",
    "canonical_job_taxonomy_active_mapping_revisions",
    "job_taxonomy_review_items",
    "company_industry_taxonomy_releases",
    "company_industry_active_revisions",
    "company_industry_review_items",
    "skill_taxonomy_releases",
    "skill_taxonomy_active_revisions",
    "alembic_version",
)


@dataclass(frozen=True)
class TargetStateReport:
    clean: bool
    issues: tuple[str, ...]


def verify_target_state(*, db_engine: Engine, metadata: MetaData) -> TargetStateReport:
    expected = set(metadata.tables)
    actual = set(inspect(db_engine).get_table_names())
    issues: list[str] = []
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if missing:
            issues.append("missing target tables: " + ", ".join(missing))
        if unexpected:
            issues.append("unexpected target tables: " + ", ".join(unexpected))
    forbidden = sorted(actual.intersection(FORBIDDEN_TABLE_NAMES))
    if forbidden:
        issues.append("forbidden version tables: " + ", ".join(forbidden))
    with db_engine.connect() as connection:
        for name in RUNTIME_TABLE_NAMES:
            table = metadata.tables.get(name)
            if table is None or name not in actual:
                continue
            count = connection.scalar(select(func.count()).select_from(table)) or 0
            if count:
                issues.append(f"runtime table is not empty: {name} ({count})")
    return TargetStateReport(clean=not issues, issues=tuple(issues))


def clear_database(*, db_engine: Engine, confirmed: bool) -> None:
    if not confirmed:
        raise ValueError("Sandbox database destruction is not confirmed")
    database_name = db_engine.url.database or ""
    if database_name != "jobsdb" and not database_name.endswith("_test"):
        raise ValueError(
            "Sandbox database clear is restricted to jobsdb or a *_test database"
        )
    if db_engine.dialect.name != "postgresql":
        raise ValueError("Sandbox database clear requires PostgreSQL")
    with db_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    remaining = inspect(db_engine).get_table_names()
    if remaining:
        raise RuntimeError(
            "Sandbox database did not clear completely: " + ", ".join(remaining)
        )


__all__ = [
    "FORBIDDEN_TABLE_NAMES",
    "RUNTIME_TABLE_NAMES",
    "TargetStateReport",
    "clear_database",
    "verify_target_state",
]
