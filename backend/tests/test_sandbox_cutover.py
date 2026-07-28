from __future__ import annotations

from pathlib import Path

from datetime import datetime, timezone
from uuid import UUID

import pytest
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, MetaData, String, Table, Uuid, create_engine, event, select

from app.database import Base
import app.models  # noqa: F401
from app.job_intelligence.sandbox_cutover import (
    FORBIDDEN_TABLE_NAMES,
    RedisRuntimeStateCleaner,
    SandboxCutover,
    VerificationReport,
    verify_target_state,
)
from app.job_intelligence.sandbox_cutover.artifacts import RetentionArtifactStore
from app.messaging.topics import ALL_STREAM_TOPICS


def _retained_metadata() -> MetaData:
    metadata = MetaData()
    Table(
        "governance_audit_events",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("domain", String, nullable=False),
        Column("before_summary", JSON, nullable=False),
        Column("after_summary", JSON, nullable=False),
    )
    return metadata


def test_export_retains_rows_but_removes_version_identity_from_audit_json(
    tmp_path: Path,
) -> None:
    metadata = _retained_metadata()
    source = create_engine("sqlite:///:memory:")
    metadata.create_all(source)
    with source.begin() as connection:
        connection.execute(
            metadata.tables["governance_audit_events"].insert(),
            {
                "id": 1,
                "domain": "job-taxonomy",
                "before_summary": {
                    "taxonomy_code": "engineering",
                    "revision_id": "old-revision",
                    "nested": {
                        "release_id": "old-release",
                        "taxonomy_revision_id": "old-taxonomy-revision",
                        "source_catalog_revision_id": "old-catalog-revision",
                        "model_version": "embedding-v1",
                        "kept": True,
                    },
                },
                "after_summary": {
                    "taxonomy_code": "technology",
                    "lock_version": 8,
                },
            },
        )

    artifact = tmp_path / "retained.json"
    report = SandboxCutover(
        source_engine=source,
        metadata=metadata,
        retained_table_names=("governance_audit_events",),
    ).export_retained(artifact)

    assert report.table_counts == {"governance_audit_events": 1}
    assert report.discarded_non_null_counts == {
        "companies.extra_data": 0,
        "jobs.search_vector": 0,
    }
    payload = SandboxCutover.read_artifact(artifact)
    assert payload["tables"][0]["rows"] == [
        {
            "after_summary": {"taxonomy_code": "technology"},
            "before_summary": {
                "nested": {"kept": True, "model_version": "embedding-v1"},
                "taxonomy_code": "engineering",
            },
            "domain": "job-taxonomy",
            "id": 1,
        }
    ]
    assert '"version":' not in artifact.read_text(encoding="utf-8")
    assert "old-revision" not in artifact.read_text(encoding="utf-8")
    assert "old-release" not in artifact.read_text(encoding="utf-8")
    assert "old-taxonomy-revision" not in artifact.read_text(encoding="utf-8")
    assert "old-catalog-revision" not in artifact.read_text(encoding="utf-8")


def test_import_and_verify_preserve_exact_retained_identity_and_content(
    tmp_path: Path,
) -> None:
    metadata = MetaData()
    companies = Table(
        "companies",
        metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True),
        Column("name", String, nullable=False),
        Column("observed_at", DateTime(timezone=True), nullable=False),
        Column("evidence", JSON, nullable=False),
    )
    source = create_engine("sqlite:///:memory:")
    target = create_engine("sqlite:///:memory:")
    metadata.create_all(source)
    metadata.create_all(target)
    company_id = UUID("12345678-1234-5678-9234-567812345678")
    observed_at = datetime(2026, 7, 27, 8, 30, tzinfo=timezone.utc)
    with source.begin() as connection:
        connection.execute(
            companies.insert(),
            {
                "id": company_id,
                "name": "Example Limited",
                "observed_at": observed_at,
                "evidence": {"source": "offertoday", "labels": ["Technology"]},
            },
        )

    artifact = tmp_path / "retained.json"
    cutover = SandboxCutover(
        source_engine=source,
        metadata=metadata,
        retained_table_names=("companies",),
    )
    before = cutover.export_retained(artifact)
    imported = cutover.import_retained(artifact, target_engine=target)
    verified = cutover.verify_retained(artifact, target_engine=target)

    assert imported.table_counts == before.table_counts
    assert verified.matched
    assert verified.mismatches == ()
    with target.connect() as connection:
        row = connection.execute(select(companies)).mappings().one()
    assert row["id"] == company_id
    assert row["name"] == "Example Limited"
    assert row["evidence"] == {"source": "offertoday", "labels": ["Technology"]}

    cutover.delete_artifact_after_verification(artifact, verified)
    assert not artifact.exists()


def test_import_orders_retained_hierarchy_parents_before_children(tmp_path: Path) -> None:
    metadata = MetaData()
    classifications = Table(
        "source_classifications",
        metadata,
        Column("id", String, primary_key=True),
        Column("parent_id", String, ForeignKey("source_classifications.id")),
        Column("label", String, nullable=False),
    )
    source = create_engine("sqlite:///:memory:")
    target = create_engine("sqlite:///:memory:")
    for candidate in (source, target):
        event.listen(
            candidate,
            "connect",
            lambda connection, _record: connection.execute("PRAGMA foreign_keys=ON"),
        )
        metadata.create_all(candidate)
    with source.begin() as connection:
        connection.execute(classifications.insert(), {"id": "z-parent", "label": "Root"})
        connection.execute(
            classifications.insert(),
            {"id": "a-child", "parent_id": "z-parent", "label": "Child"},
        )

    artifact = tmp_path / "hierarchy.json"
    cutover = SandboxCutover(
        source_engine=source,
        metadata=metadata,
        retained_table_names=("source_classifications",),
    )
    cutover.export_retained(artifact)

    cutover.import_retained(artifact, target_engine=target)

    with target.connect() as connection:
        assert connection.execute(select(classifications.c.id)).scalars().all() == [
            "a-child",
            "z-parent",
        ]


def test_transient_artifact_is_kept_when_verification_failed(tmp_path: Path) -> None:
    artifact = tmp_path / "retained.json"
    artifact.write_text("keep-me", encoding="utf-8")

    with pytest.raises(ValueError, match="verification has not passed"):
        SandboxCutover.delete_artifact_after_verification(
            artifact,
            VerificationReport(matched=False, mismatches=("companies: hash mismatch",)),
        )

    assert artifact.read_text(encoding="utf-8") == "keep-me"


def test_destroy_gate_rejects_artifact_without_complete_retained_table_set(
    tmp_path: Path,
) -> None:
    metadata = _retained_metadata()
    source = create_engine("sqlite:///:memory:")
    metadata.create_all(source)
    artifact = tmp_path / "incomplete.json"
    RetentionArtifactStore().write(
        artifact,
        {
            "discarded_non_null_counts": {
                "companies.extra_data": 0,
                "jobs.search_vector": 0,
            },
            "tables": [],
        },
    )
    cutover = SandboxCutover(
        source_engine=source,
        metadata=metadata,
        retained_table_names=("governance_audit_events",),
    )

    with pytest.raises(ValueError, match="table set or order"):
        cutover.validate_artifact(artifact)


def test_export_reports_removed_column_counts_and_omits_their_values(
    tmp_path: Path,
) -> None:
    target_metadata = MetaData()
    Table(
        "companies",
        target_metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
        Column("website", String, nullable=True),
    )
    Table(
        "jobs",
        target_metadata,
        Column("id", Integer, primary_key=True),
        Column("title", String, nullable=False),
    )
    source_metadata = MetaData()
    companies = Table(
        "companies",
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String, nullable=False),
        Column("extra_data", JSON, nullable=True),
    )
    jobs = Table(
        "jobs",
        source_metadata,
        Column("id", Integer, primary_key=True),
        Column("title", String, nullable=False),
        Column("search_vector", String, nullable=True),
    )
    source = create_engine("sqlite:///:memory:")
    source_metadata.create_all(source)
    with source.begin() as connection:
        connection.execute(
            companies.insert(),
            [
                {"id": 1, "name": "One", "extra_data": {"legacy": True}},
                {"id": 2, "name": "Two", "extra_data": None},
            ],
        )
        connection.execute(
            jobs.insert(),
            {"id": 1, "title": "Engineer", "search_vector": "engineer"},
        )

    artifact = tmp_path / "removed-columns.json"
    report = SandboxCutover(
        source_engine=source,
        metadata=target_metadata,
        retained_table_names=("companies", "jobs"),
    ).export_retained(artifact)

    assert report.discarded_non_null_counts == {
        "companies.extra_data": 2,
        "jobs.search_vector": 1,
    }
    payload = SandboxCutover.read_artifact(artifact)
    company_rows = payload["tables"][0]["rows"]
    job_rows = payload["tables"][1]["rows"]
    assert all("extra_data" not in row for row in company_rows)
    assert all("search_vector" not in row for row in job_rows)
    assert company_rows[0]["website"] is None


def test_redis_cleanup_deletes_every_stream_with_groups_pending_and_dead_letters() -> None:
    class FakeRedis:
        def __init__(self) -> None:
            self.keys = set(ALL_STREAM_TOPICS) | {"unrelated-cache"}
            self.deleted: tuple[str, ...] = ()

        def delete(self, *names: str) -> int:
            self.deleted = names
            removed = sum(name in self.keys for name in names)
            self.keys.difference_update(names)
            return removed

        def exists(self, name: str) -> int:
            return int(name in self.keys)

    redis_client = FakeRedis()

    report = RedisRuntimeStateCleaner(redis_client).clear()

    assert redis_client.deleted == tuple(sorted(ALL_STREAM_TOPICS))
    assert report.cleared_topics == tuple(sorted(ALL_STREAM_TOPICS))
    assert redis_client.keys == {"unrelated-cache"}


def test_current_metadata_has_no_release_revision_review_or_legacy_taxonomy_tables() -> None:
    table_names = set(Base.metadata.tables)
    forbidden_fragments = (
        "revision",
        "release",
        "review_item",
        "job_domains",
        "job_categories",
        "job_subcategories",
        "skill_categories",
        "skill_technologies",
        "governed_",
    )

    assert not table_names.intersection(FORBIDDEN_TABLE_NAMES)
    assert {
        name
        for name in table_names
        if any(fragment in name for fragment in forbidden_fragments)
    } == set()


def test_target_verification_requires_all_runtime_history_tables_empty() -> None:
    metadata = MetaData()
    runtime = Table(
        "crawl_jobs",
        metadata,
        Column("id", Integer, primary_key=True),
    )
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    assert verify_target_state(db_engine=engine, metadata=metadata).clean
    with engine.begin() as connection:
        connection.execute(runtime.insert(), {"id": 1})

    report = verify_target_state(db_engine=engine, metadata=metadata)
    assert not report.clean
    assert report.issues == ("runtime table is not empty: crawl_jobs (1)",)


def test_operator_cli_contains_no_backup_restore_rollback_or_version_command() -> None:
    from scripts.sandbox_cutover import build_parser

    help_text = build_parser().format_help().lower()

    for retired_word in ("backup", "restore", "rollback", "revision", "release"):
        assert retired_word not in help_text
