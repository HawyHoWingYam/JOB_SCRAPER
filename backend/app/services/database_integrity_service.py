from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.sqltypes import DateTime

from app.database import Base, SessionLocal
from app.models import (
    CrawlJobListing,
    EventOutbox,
    Job,
    JobCategory,
    JobDomain,
    JobEmbedding,
    JobSubcategory,
    ScheduleExecution,
    Skill,
    SkillCategory,
    SkillCandidate,
    SkillTaxonomyActiveRevision,
    SkillTaxonomyRelease,
    SkillTechnology,
    GovernedJobSkill,
    GovernedJobSkillMention,
    GovernedSkill,
    GovernedSkillAlias,
    GovernedSkillCategory,
    GovernedSkillTechnology,
)
from app.utils.time import utc_now

EXPECTED_EXTERNAL_TABLES = ("apscheduler_jobs",)

TAXONOMY_SEED_MODELS = (
    ("job_domains", JobDomain),
    ("job_categories", JobCategory),
    ("job_subcategories", JobSubcategory),
    ("skill_categories", SkillCategory),
    ("skill_technologies", SkillTechnology),
    ("skills", Skill),
)

GOVERNED_SKILL_MODELS = (
    ("skill_taxonomy_releases", SkillTaxonomyRelease),
    ("skill_taxonomy_active_revisions", SkillTaxonomyActiveRevision),
    ("governed_skill_categories", GovernedSkillCategory),
    ("governed_skill_technologies", GovernedSkillTechnology),
    ("governed_skills", GovernedSkill),
    ("governed_skill_aliases", GovernedSkillAlias),
    ("skill_candidates", SkillCandidate),
    ("governed_job_skill_mentions", GovernedJobSkillMention),
    ("governed_job_skills", GovernedJobSkill),
)

ADVISORY_SCHEMA_EXPECTATIONS = (
    {
        "id": "crawl_job_listings_crawl_job_id_fk",
        "kind": "foreign_key",
        "table": "crawl_job_listings",
        "columns": ["crawl_job_id"],
        "referred_table": "crawl_jobs",
        "message": "crawl_job_listings.crawl_job_id is not enforced as a database foreign key",
    },
    {
        "id": "crawl_job_listings_last_detail_crawl_job_id_fk",
        "kind": "foreign_key",
        "table": "crawl_job_listings",
        "columns": ["last_detail_crawl_job_id"],
        "referred_table": "crawl_jobs",
        "message": "crawl_job_listings.last_detail_crawl_job_id is not enforced as a database foreign key",
    },
    {
        "id": "crawl_job_listings_published_job_id_fk",
        "kind": "foreign_key",
        "table": "crawl_job_listings",
        "columns": ["published_job_id"],
        "referred_table": "jobs",
        "message": "crawl_job_listings.published_job_id is not enforced as a database foreign key",
    },
    {
        "id": "event_outbox_domain_event_unique_key",
        "kind": "unique_constraint",
        "table": "event_outbox",
        "columns": ["aggregate_type", "aggregate_id", "event_type"],
        "message": "event_outbox has no database uniqueness guard for duplicate domain events",
    },
    {
        "id": "job_embeddings_embedding_ann_index",
        "kind": "index",
        "table": "job_embeddings",
        "columns": ["embedding"],
        "message": "job_embeddings.embedding has no ANN vector index",
    },
)


def _coerce_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _isoformat_or_none(value: Any) -> str | None:
    return (
        value.isoformat() if value is not None and hasattr(value, "isoformat") else None
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_seconds(reference_time: datetime, value: datetime | None) -> int:
    normalized = _as_utc(value)
    if normalized is None:
        return 0
    return max(int((reference_time - normalized).total_seconds()), 0)


def _ratio(
    numerator: int, denominator: int, *, empty_value: float = 0.0
) -> float | None:
    if denominator <= 0:
        return empty_value if numerator <= 0 else None
    return round(numerator / denominator, 2)


def _default_expected_tables() -> list[str]:
    return sorted(set(Base.metadata.tables) | set(EXPECTED_EXTERNAL_TABLES))


def _table_exists(table_name: str, observed_tables: set[str]) -> bool:
    return table_name in observed_tables


def _safe_group_counts(
    db: Any, model: Any, column: Any, *, observed_tables: set[str]
) -> dict[str, int]:
    if not _table_exists(model.__tablename__, observed_tables):
        return {}
    try:
        rows = db.query(column, func.count()).group_by(column).all()
    except SQLAlchemyError:
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            rollback()
        return {}
    return {str(key): int(count) for key, count in rows}


def _safe_count(db: Any, model: Any, *criteria: Any, observed_tables: set[str]) -> int:
    if not _table_exists(model.__tablename__, observed_tables):
        return 0
    query = db.query(func.count()).select_from(model.__table__)
    if criteria:
        query = query.filter(*criteria)
    try:
        return int(query.scalar() or 0)
    except SQLAlchemyError:
        rollback = getattr(db, "rollback", None)
        if callable(rollback):
            rollback()
        return 0


def _load_schema_summary(
    db: Any, expected_tables: Iterable[str] | None
) -> dict[str, Any]:
    inspector = inspect(db.get_bind())
    observed_tables = sorted(inspector.get_table_names())
    expected = sorted(set(expected_tables or _default_expected_tables()))
    missing = sorted(set(expected) - set(observed_tables))
    unexpected = sorted(set(observed_tables) - set(expected))
    observed_columns: dict[str, list[str]] = {}
    missing_columns: list[str] = []
    for table_name in sorted(set(expected) & set(observed_tables)):
        try:
            column_names = sorted(
                str(column.get("name")) for column in inspector.get_columns(table_name)
            )
        except SQLAlchemyError:
            column_names = []
        observed_columns[table_name] = column_names
        expected_table = Base.metadata.tables.get(table_name)
        if expected_table is None:
            continue
        for column in expected_table.columns:
            if column.name not in column_names:
                missing_columns.append(f"{table_name}.{column.name}")
    return {
        "expected_tables": expected,
        "observed_tables": observed_tables,
        "missing_expected_tables": missing,
        "unexpected_tables": unexpected,
        "observed_columns": observed_columns,
        "missing_expected_columns": sorted(missing_columns),
    }


def _has_foreign_key(
    inspector: Any, table_name: str, columns: list[str], referred_table: str
) -> bool:
    try:
        foreign_keys = inspector.get_foreign_keys(table_name)
    except SQLAlchemyError:
        return False
    expected_columns = tuple(columns)
    for foreign_key in foreign_keys:
        constrained = tuple(foreign_key.get("constrained_columns") or [])
        referred = str(foreign_key.get("referred_table") or "")
        if constrained == expected_columns and referred == referred_table:
            return True
    return False


def _has_unique_constraint(inspector: Any, table_name: str, columns: list[str]) -> bool:
    expected = tuple(columns)
    try:
        unique_constraints = inspector.get_unique_constraints(table_name)
        indexes = inspector.get_indexes(table_name)
    except SQLAlchemyError:
        return False
    for constraint in unique_constraints:
        if tuple(constraint.get("column_names") or []) == expected:
            return True
    for index in indexes:
        if index.get("unique") and tuple(index.get("column_names") or []) == expected:
            return True
    return False


def _has_embedding_ann_index(inspector: Any, table_name: str) -> bool:
    try:
        indexes = inspector.get_indexes(table_name)
    except SQLAlchemyError:
        return False
    for index in indexes:
        name = str(index.get("name") or "").lower()
        columns = {str(column).lower() for column in (index.get("column_names") or [])}
        if "embedding" not in columns:
            continue
        if (
            "hnsw" in name
            or "ivfflat" in name
            or name == "ix_job_embeddings_embedding_hnsw"
        ):
            return True
    return False


def _load_advisory_findings(db: Any, observed_tables: set[str]) -> list[dict[str, Any]]:
    inspector = inspect(db.get_bind())
    findings: list[dict[str, Any]] = []
    for expectation in ADVISORY_SCHEMA_EXPECTATIONS:
        table_name = str(expectation["table"])
        if table_name not in observed_tables:
            continue
        kind = expectation["kind"]
        columns = list(expectation.get("columns") or [])
        present = False
        if kind == "foreign_key":
            present = _has_foreign_key(
                inspector,
                table_name,
                columns,
                str(expectation.get("referred_table") or ""),
            )
        elif kind == "unique_constraint":
            present = _has_unique_constraint(inspector, table_name, columns)
        elif (
            kind == "index"
            and expectation["id"] == "job_embeddings_embedding_ann_index"
        ):
            present = _has_embedding_ann_index(inspector, table_name)

        if not present:
            findings.append(
                {
                    "id": expectation["id"],
                    "severity": "advisory",
                    "kind": kind,
                    "table": table_name,
                    "columns": columns,
                    "message": expectation["message"],
                }
            )
    return findings


def _load_timestamp_mix(expected_tables: Iterable[str] | None = None) -> dict[str, Any]:
    expected = set(expected_tables or _default_expected_tables())
    aware: list[str] = []
    naive: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in expected:
            continue
        for column in table.columns:
            if isinstance(column.type, DateTime):
                key = f"{table.name}.{column.name}"
                if bool(getattr(column.type, "timezone", False)):
                    aware.append(key)
                else:
                    naive.append(key)
    return {
        "timezone_aware_count": len(aware),
        "timezone_naive_count": len(naive),
        "timezone_aware_columns": sorted(aware),
        "timezone_naive_columns": sorted(naive),
        "mixed": bool(aware and naive),
    }


def _load_staging_summary(db: Any, observed_tables: set[str]) -> dict[str, Any]:
    total = _safe_count(db, CrawlJobListing, observed_tables=observed_tables)
    published_rows = _safe_count(
        db,
        CrawlJobListing,
        CrawlJobListing.published_job_id.isnot(None),
        observed_tables=observed_tables,
    )
    published_jobs = _safe_count(
        db,
        Job,
        Job.is_deleted.is_(False),
        observed_tables=observed_tables,
    )
    return {
        "total_staged_rows": total,
        "staged_published_rows": published_rows,
        "staged_unpublished_rows": max(total - published_rows, 0),
        "published_jobs": published_jobs,
        "staged_to_published_ratio": _ratio(total, published_jobs),
    }


def _load_duplicate_summary(db: Any, observed_tables: set[str]) -> dict[str, Any]:
    summary = {
        "jobs_source_key_duplicate_groups": 0,
        "jobs_source_key_examples": [],
        "crawl_job_listings_source_key_duplicate_groups": 0,
        "crawl_job_listings_source_key_examples": [],
    }

    if "jobs" in observed_tables:
        rows = (
            db.execute(
                text(
                    """
                SELECT source_site, source_job_id, COUNT(*) AS duplicate_count
                FROM jobs
                WHERE source_site IS NOT NULL AND source_job_id IS NOT NULL
                GROUP BY source_site, source_job_id
                HAVING COUNT(*) > 1
                ORDER BY duplicate_count DESC, source_site ASC, source_job_id ASC
                LIMIT 10
                """
                )
            )
            .mappings()
            .all()
        )
        summary["jobs_source_key_duplicate_groups"] = len(rows)
        summary["jobs_source_key_examples"] = [
            {
                "source_site": str(row["source_site"]),
                "source_job_id": str(row["source_job_id"]),
                "count": int(row["duplicate_count"]),
            }
            for row in rows
        ]

    if "crawl_job_listings" in observed_tables:
        rows = (
            db.execute(
                text(
                    """
                SELECT crawl_job_id, source_site, source_job_id, COUNT(*) AS duplicate_count
                FROM crawl_job_listings
                WHERE crawl_job_id IS NOT NULL
                  AND source_site IS NOT NULL
                  AND source_job_id IS NOT NULL
                GROUP BY crawl_job_id, source_site, source_job_id
                HAVING COUNT(*) > 1
                ORDER BY duplicate_count DESC, crawl_job_id ASC, source_site ASC, source_job_id ASC
                LIMIT 10
                """
                )
            )
            .mappings()
            .all()
        )
        summary["crawl_job_listings_source_key_duplicate_groups"] = len(rows)
        summary["crawl_job_listings_source_key_examples"] = [
            {
                "crawl_job_id": str(row["crawl_job_id"]),
                "source_site": str(row["source_site"]),
                "source_job_id": str(row["source_job_id"]),
                "count": int(row["duplicate_count"]),
            }
            for row in rows
        ]

    return summary


def _load_outbox_summary(
    db: Any, observed_tables: set[str], reference_time: datetime
) -> dict[str, Any]:
    status_counts = _safe_group_counts(
        db, EventOutbox, EventOutbox.status, observed_tables=observed_tables
    )
    if not _table_exists(EventOutbox.__tablename__, observed_tables):
        return {
            "status_counts": status_counts,
            "retrying_rows": 0,
            "max_attempts": 0,
            "oldest_pending_age_seconds": 0,
        }

    retrying_rows = (
        db.query(EventOutbox)
        .filter(EventOutbox.status == "pending", EventOutbox.attempt_count > 0)
        .count()
    )
    max_attempts = db.query(func.max(EventOutbox.attempt_count)).scalar()
    oldest_pending_created_at = (
        db.query(func.min(EventOutbox.created_at))
        .filter(EventOutbox.status == "pending")
        .scalar()
    )
    return {
        "status_counts": status_counts,
        "retrying_rows": int(retrying_rows),
        "max_attempts": _coerce_int(max_attempts),
        "oldest_pending_age_seconds": _age_seconds(
            reference_time, oldest_pending_created_at
        ),
    }


def _load_taxonomy_summary(db: Any, observed_tables: set[str]) -> dict[str, Any]:
    seed_counts: dict[str, int] = {}
    for table_name, model in TAXONOMY_SEED_MODELS:
        seed_counts[table_name] = _safe_count(
            db, model, observed_tables=observed_tables
        )
    empty = [table_name for table_name, count in seed_counts.items() if count == 0]
    legacy_seed = {
        "seed_table_counts": seed_counts,
        "empty_seed_tables": empty,
        "all_seed_tables_empty": len(empty) == len(seed_counts),
    }
    return {
        **legacy_seed,
        "legacy_seed": legacy_seed,
        "governed_skill": _load_governed_skill_summary(db, observed_tables),
    }


def _load_governed_skill_summary(
    db: Any,
    observed_tables: set[str],
) -> dict[str, Any]:
    table_counts = {
        table_name: _safe_count(db, model, observed_tables=observed_tables)
        for table_name, model in GOVERNED_SKILL_MODELS
    }
    missing_tables = [
        table_name
        for table_name, _ in GOVERNED_SKILL_MODELS
        if table_name not in observed_tables
    ]
    summary: dict[str, Any] = {
        "available": not missing_tables,
        "missing_tables": missing_tables,
        "table_counts": table_counts,
        "release_status_counts": _safe_group_counts(
            db,
            SkillTaxonomyRelease,
            SkillTaxonomyRelease.status,
            observed_tables=observed_tables,
        ),
        "active_revision": None,
        "release_count_mismatches": [],
        "resolved_candidates_without_audit": 0,
        "operator_skills_without_audit": 0,
        "operator_aliases_without_audit": 0,
        "integrity_issues": [],
    }
    if missing_tables:
        return summary

    release_count_mismatches: list[dict[str, Any]] = []
    releases = (
        db.query(SkillTaxonomyRelease)
        .order_by(
            SkillTaxonomyRelease.created_at.asc(),
            SkillTaxonomyRelease.revision_id.asc(),
        )
        .all()
    )
    for release in releases:
        if release.status != "ready":
            continue
        expected = {
            "categories": int(release.expected_category_count),
            "technologies": int(release.expected_technology_count),
            "skills": int(release.expected_skill_count),
            "aliases": int(release.expected_alias_count),
        }
        actual = {
            "categories": _safe_count(
                db,
                GovernedSkillCategory,
                GovernedSkillCategory.revision_id == release.revision_id,
                observed_tables=observed_tables,
            ),
            "technologies": _safe_count(
                db,
                GovernedSkillTechnology,
                GovernedSkillTechnology.revision_id == release.revision_id,
                observed_tables=observed_tables,
            ),
            "skills": _safe_count(
                db,
                GovernedSkill,
                GovernedSkill.revision_id == release.revision_id,
                GovernedSkill.origin == "seed",
                observed_tables=observed_tables,
            ),
            "aliases": _safe_count(
                db,
                GovernedSkillAlias,
                GovernedSkillAlias.taxonomy_revision_id == release.revision_id,
                GovernedSkillAlias.source != "operator",
                observed_tables=observed_tables,
            ),
        }
        if actual != expected:
            release_count_mismatches.append(
                {
                    "revision_id": str(release.revision_id),
                    "expected": expected,
                    "actual": actual,
                }
            )

    active = db.get(SkillTaxonomyActiveRevision, "skill-taxonomy")
    if active is not None:
        release = db.get(SkillTaxonomyRelease, active.revision_id)
        valid = bool(
            release is not None
            and release.status == "ready"
            and release.content_hash == active.content_hash
        )
        summary["active_revision"] = {
            "revision_id": str(active.revision_id),
            "content_hash": active.content_hash,
            "lock_version": int(active.lock_version),
            "state": "ready" if valid else "invalid",
        }
        if not valid:
            summary["integrity_issues"].append(
                "active revision does not identify a matching ready release"
            )

    summary["release_count_mismatches"] = release_count_mismatches
    if release_count_mismatches:
        summary["integrity_issues"].append(
            f"{len(release_count_mismatches)} ready release(s) have seed count drift"
        )

    summary["resolved_candidates_without_audit"] = _safe_count(
        db,
        SkillCandidate,
        SkillCandidate.status != "pending",
        SkillCandidate.decision_audit_id.is_(None),
        observed_tables=observed_tables,
    )
    summary["operator_skills_without_audit"] = _safe_count(
        db,
        GovernedSkill,
        GovernedSkill.origin == "operator",
        GovernedSkill.created_by_audit_id.is_(None),
        observed_tables=observed_tables,
    )
    summary["operator_aliases_without_audit"] = _safe_count(
        db,
        GovernedSkillAlias,
        GovernedSkillAlias.source == "operator",
        GovernedSkillAlias.created_by_audit_id.is_(None),
        observed_tables=observed_tables,
    )
    for key, label in (
        ("resolved_candidates_without_audit", "resolved Candidates"),
        ("operator_skills_without_audit", "operator-created Skills"),
        ("operator_aliases_without_audit", "operator-created aliases"),
    ):
        count = int(summary[key])
        if count:
            summary["integrity_issues"].append(
                f"{count} {label} are missing governance audit references"
            )
    return summary


def _load_embedding_summary(db: Any, observed_tables: set[str]) -> dict[str, Any]:
    total_jobs = _safe_count(
        db,
        Job,
        Job.is_deleted.is_(False),
        observed_tables=observed_tables,
    )
    current_embeddings = _safe_count(db, JobEmbedding, observed_tables=observed_tables)
    missing_current_embeddings = max(total_jobs - current_embeddings, 0)
    vector_index_present = False
    if "job_embeddings" in observed_tables:
        vector_index_present = _has_embedding_ann_index(
            inspect(db.get_bind()), "job_embeddings"
        )
    return {
        "total_jobs": total_jobs,
        "current_embeddings": current_embeddings,
        "missing_current_embeddings": missing_current_embeddings,
        "coverage_ratio": _ratio(current_embeddings, total_jobs, empty_value=1.0),
        "vector_index_present": vector_index_present,
    }


def _load_enrichment_counter_drift(
    db: Any, observed_tables: set[str]
) -> dict[str, int]:
    visible_without_distinct = 0
    usage_without_distinct = 0
    for _, model in TAXONOMY_SEED_MODELS:
        if not _table_exists(model.__tablename__, observed_tables):
            continue
        visible_without_distinct += _safe_count(
            db,
            model,
            model.is_filter_visible.is_(True),
            model.distinct_job_count == 0,
            observed_tables=observed_tables,
        )
        usage_without_distinct += _safe_count(
            db,
            model,
            model.usage_count > 0,
            model.distinct_job_count == 0,
            observed_tables=observed_tables,
        )
    return {
        "visible_nodes_without_distinct_job_count": visible_without_distinct,
        "usage_nodes_without_distinct_job_count": usage_without_distinct,
    }


def _load_scheduler_integrity(db: Any, observed_tables: set[str]) -> dict[str, int]:
    if not _table_exists(ScheduleExecution.__tablename__, observed_tables):
        return {"executions_missing_request_payload_snapshot": 0}
    inspector = inspect(db.get_bind())
    try:
        column_names = {
            str(column.get("name"))
            for column in inspector.get_columns(ScheduleExecution.__tablename__)
        }
    except SQLAlchemyError:
        column_names = set()
    if "request_payload_snapshot" not in column_names:
        return {"executions_missing_request_payload_snapshot": 0}
    missing_snapshots = _safe_count(
        db,
        ScheduleExecution,
        ScheduleExecution.request_payload_snapshot.is_(None),
        observed_tables=observed_tables,
    )
    return {"executions_missing_request_payload_snapshot": missing_snapshots}


def _derive_status_and_issues(
    *,
    schema: dict[str, Any],
    staging: dict[str, Any],
    duplicates: dict[str, Any],
    detail_status_counts: dict[str, int],
    outbox: dict[str, Any],
    taxonomy: dict[str, Any],
    embeddings: dict[str, Any],
    enrichment_counter_drift: dict[str, int],
    scheduler: dict[str, int],
) -> tuple[str, list[str]]:
    issues: list[str] = []
    critical = False
    degraded = False

    missing_tables = list(schema.get("missing_expected_tables") or [])
    if missing_tables:
        critical = True
        issues.append(f"missing expected database tables: {', '.join(missing_tables)}")
    missing_columns = list(schema.get("missing_expected_columns") or [])
    if missing_columns:
        critical = True
        issues.append(
            f"missing expected database columns: {', '.join(missing_columns)}"
        )

    duplicate_job_groups = _coerce_int(
        duplicates.get("jobs_source_key_duplicate_groups")
    )
    if duplicate_job_groups:
        critical = True
        issues.append(
            f"jobs has {duplicate_job_groups} duplicate source job key groups"
        )

    duplicate_listing_groups = _coerce_int(
        duplicates.get("crawl_job_listings_source_key_duplicate_groups")
    )
    if duplicate_listing_groups:
        critical = True
        issues.append(
            f"crawl_job_listings has {duplicate_listing_groups} duplicate staged source key groups"
        )

    staged_unpublished = _coerce_int(staging.get("staged_unpublished_rows"))
    if staged_unpublished:
        degraded = True
        issues.append(
            f"crawl_job_listings has {staged_unpublished} staged rows without published_job_id"
        )

    for status_name in ("pending", "failed", "manual_action_required"):
        count = _coerce_int(detail_status_counts.get(status_name))
        if count:
            degraded = True
            issues.append(
                f"crawl_job_listings detail_status {status_name} has {count} rows"
            )

    outbox_counts = dict(outbox.get("status_counts") or {})
    for status_name in ("pending", "failed"):
        count = _coerce_int(outbox_counts.get(status_name))
        if count:
            degraded = True
            issues.append(f"event_outbox has {count} {status_name} rows")
    retrying_rows = _coerce_int(outbox.get("retrying_rows"))
    if retrying_rows:
        degraded = True
        issues.append(f"event_outbox has {retrying_rows} retrying rows")

    if taxonomy.get("all_seed_tables_empty"):
        degraded = True
        issues.append("taxonomy seed tables are empty")

    governed_skill_issues = list(
        (taxonomy.get("governed_skill") or {}).get("integrity_issues") or []
    )
    if governed_skill_issues:
        critical = True
        issues.extend(
            f"governed Skill integrity: {issue}" for issue in governed_skill_issues
        )

    missing_embeddings = _coerce_int(embeddings.get("missing_current_embeddings"))
    if missing_embeddings:
        degraded = True
        issues.append(f"embeddings missing for {missing_embeddings} current jobs")

    visible_drift = _coerce_int(
        enrichment_counter_drift.get("visible_nodes_without_distinct_job_count")
    )
    usage_drift = _coerce_int(
        enrichment_counter_drift.get("usage_nodes_without_distinct_job_count")
    )
    if visible_drift or usage_drift:
        degraded = True
        issues.append(
            "taxonomy enrichment counters have drift "
            f"(visible_without_distinct={visible_drift}, usage_without_distinct={usage_drift})"
        )

    missing_snapshots = _coerce_int(
        scheduler.get("executions_missing_request_payload_snapshot")
    )
    if missing_snapshots:
        degraded = True
        issues.append(
            f"schedule_executions has {missing_snapshots} rows missing request_payload_snapshot"
        )

    status = "critical" if critical else "degraded" if degraded else "healthy"
    return status, issues


def build_database_integrity_summary(
    *,
    session_factory: Callable[[], Any] = SessionLocal,
    expected_tables: Iterable[str] | None = None,
    reference_time: datetime | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    reference = _as_utc(reference_time or utc_now()) or utc_now()
    generated = generated_at or reference
    db = session_factory()
    try:
        schema = _load_schema_summary(db, expected_tables)
        observed_tables = set(schema["observed_tables"])
        detail_status_counts = _safe_group_counts(
            db,
            CrawlJobListing,
            CrawlJobListing.detail_status,
            observed_tables=observed_tables,
        )
        staging = _load_staging_summary(db, observed_tables)
        duplicates = _load_duplicate_summary(db, observed_tables)
        outbox = _load_outbox_summary(db, observed_tables, reference)
        taxonomy = _load_taxonomy_summary(db, observed_tables)
        embeddings = _load_embedding_summary(db, observed_tables)
        enrichment_counter_drift = _load_enrichment_counter_drift(db, observed_tables)
        scheduler = _load_scheduler_integrity(db, observed_tables)
        status, issues = _derive_status_and_issues(
            schema=schema,
            staging=staging,
            duplicates=duplicates,
            detail_status_counts=detail_status_counts,
            outbox=outbox,
            taxonomy=taxonomy,
            embeddings=embeddings,
            enrichment_counter_drift=enrichment_counter_drift,
            scheduler=scheduler,
        )

        return {
            "status": status,
            "generated_at": _isoformat_or_none(generated),
            "issues": issues,
            "schema": schema,
            "advisory_findings": _load_advisory_findings(db, observed_tables),
            "timestamp_mix": _load_timestamp_mix(expected_tables),
            "staging": staging,
            "duplicates": duplicates,
            "detail_status_counts": detail_status_counts,
            "outbox": outbox,
            "taxonomy": taxonomy,
            "embeddings": embeddings,
            "enrichment_counter_drift": enrichment_counter_drift,
            "scheduler": scheduler,
        }
    finally:
        db.close()
