from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, MetaData, func, inspect, select, text

from app.job_intelligence.source_attributes import EMPLOYMENT_TYPE_SEEDS


RUNTIME_TABLE_NAMES = (
    "automation_delete_reviews",
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
    "job_embeddings",
    "offertoday_keyword_csv_reviews",
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
    actual, issues = _target_schema_issues(db_engine=db_engine, metadata=metadata)
    with db_engine.connect() as connection:
        issues.extend(
            _employment_type_registry_issues(
                connection=connection,
                metadata=metadata,
                actual_table_names=actual,
            )
        )
        for name in RUNTIME_TABLE_NAMES:
            table = metadata.tables.get(name)
            if table is None or name not in actual:
                continue
            count = connection.scalar(select(func.count()).select_from(table)) or 0
            if count:
                issues.append(f"runtime table is not empty: {name} ({count})")
    return TargetStateReport(clean=not issues, issues=tuple(issues))


def verify_post_cutover_state(
    *, db_engine: Engine, metadata: MetaData
) -> TargetStateReport:
    """Verify the restarted stack before deleting the transient artifact."""

    actual, issues = _target_schema_issues(db_engine=db_engine, metadata=metadata)
    jobs = metadata.tables.get("jobs")
    embeddings = metadata.tables.get("job_embeddings")
    if jobs is None or embeddings is None:
        issues.append("post-cutover embedding tables are not registered")
        return TargetStateReport(clean=False, issues=tuple(issues))
    if "jobs" not in actual or "job_embeddings" not in actual:
        return TargetStateReport(clean=False, issues=tuple(issues))

    with db_engine.connect() as connection:
        issues.extend(
            _employment_type_registry_issues(
                connection=connection,
                metadata=metadata,
                actual_table_names=actual,
            )
        )
        job_count = connection.scalar(select(func.count()).select_from(jobs)) or 0
        embedding_count = (
            connection.scalar(select(func.count()).select_from(embeddings)) or 0
        )
        missing_count = (
            connection.scalar(
                select(func.count())
                .select_from(
                    jobs.outerjoin(
                        embeddings,
                        embeddings.c.job_id == jobs.c.id,
                    )
                )
                .where(embeddings.c.job_id.is_(None))
            )
            or 0
        )
        invalid_dimension_count = (
            connection.scalar(
                select(func.count())
                .select_from(embeddings)
                .where(embeddings.c.embedding_dimensions != 384)
            )
            or 0
        )
    if embedding_count != job_count:
        issues.append(
            "post-cutover embedding count differs from jobs: "
            f"jobs={job_count}, embeddings={embedding_count}"
        )
    if missing_count:
        issues.append(f"jobs missing post-cutover embeddings: {missing_count}")
    if invalid_dimension_count:
        issues.append(
            "post-cutover embeddings have invalid dimensions: "
            f"{invalid_dimension_count}"
        )
    return TargetStateReport(clean=not issues, issues=tuple(issues))


def _employment_type_registry_issues(
    *,
    connection,
    metadata: MetaData,
    actual_table_names: set[str],
) -> list[str]:
    table = metadata.tables.get("employment_types")
    if table is None or "employment_types" not in actual_table_names:
        return []
    expected = tuple(EMPLOYMENT_TYPE_SEEDS)
    actual = tuple(
        connection.execute(
            select(table.c.code, table.c.label, table.c.sort_order).order_by(
                table.c.sort_order,
                table.c.code,
            )
        ).tuples()
    )
    if actual == expected:
        return []
    return ["Employment Type registry differs from the canonical seven-row seed"]


def _target_schema_issues(
    *, db_engine: Engine, metadata: MetaData
) -> tuple[set[str], list[str]]:
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
    return actual, issues


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
    "verify_post_cutover_state",
    "verify_target_state",
]
