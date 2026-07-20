from __future__ import annotations

from datetime import timedelta
import hashlib
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url

from app.crawl_control.cutover import (
    RESET_CONFIRMATION,
    RESET_TABLES,
    CrawlControlCutover,
    CrawlControlCutoverReport,
)
from app.database import Base
import app.models  # noqa: F401
from app.job_intelligence.cutover.constants import KNOWN_WRITERS
from app.job_intelligence.cutover.contracts import WriterStateEvidence
from app.utils.time import utc_now
from scripts.bootstrap_db import _run_alembic, bootstrap_database


class _StoppedWriterStateProvider:
    def collect(self, *, writers, observed_at):
        return tuple(
            WriterStateEvidence(
                writer=writer,
                state="stopped",
                evidence_kind="process",
                evidence_ref=f"test:{writer}:stopped",
                observed_at=observed_at,
            )
            for writer in writers
        )


def _test_database_url() -> str:
    database_url = os.getenv("CRAWL_CONTROL_POSTGRES_TEST_URL", "").strip()
    if not database_url:
        pytest.skip("CRAWL_CONTROL_POSTGRES_TEST_URL is not configured")
    database_name = make_url(database_url).database
    if database_name is None or not database_name.endswith("_test"):
        raise RuntimeError(
            "CRAWL_CONTROL_POSTGRES_TEST_URL database name must end in _test"
        )
    return database_url


@pytest.fixture()
def postgres_cutover_engine():
    database_url = _test_database_url()
    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    bootstrap_database(db_engine=engine, metadata=Base.metadata)
    _seed_cutover_fixture(engine)
    try:
        yield engine
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
        engine.dispose()


def _seed_cutover_fixture(engine) -> None:
    tables = Base.metadata.tables
    now = utc_now()
    company_id = uuid4()
    job_id = uuid4()
    automation_id = uuid4()
    crawl_job_id = uuid4()
    plan_id = uuid4()
    listing_id = uuid4()
    target_id = uuid4()
    plan_fingerprint = "d" * 64
    catalog_revision_ids: dict[str, object] = {}

    with engine.begin() as connection:
        connection.execute(
            tables["companies"].insert().values(
                id=company_id,
                company_id="preserved-company",
                source_site="jobsdb",
                source_company_id="preserved-company",
                name="Preserved Company",
                is_deleted=False,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            tables["jobs"].insert().values(
                id=job_id,
                job_id="preserved-job",
                source_site="jobsdb",
                source_job_id="preserved-job",
                company_id=company_id,
                title="Preserved Job",
                is_deleted=False,
                created_at=now,
                updated_at=now,
            )
        )

        for sequence, source in enumerate(
            ("ctgoodjobs", "jobsdb", "offertoday"), start=1
        ):
            candidate_id = uuid4()
            revision_id = uuid4()
            fingerprint = hashlib.sha256(source.encode()).hexdigest()
            connection.execute(
                tables["source_catalog_candidates"].insert().values(
                    id=candidate_id,
                    source_site=source,
                    fingerprint=fingerprint,
                    normalized_payload={"source_site": source, "nodes": []},
                    source_payload={"fixture": True},
                    provenance={"kind": "test"},
                    diff={},
                    validation_summary={"status": "passed"},
                    state="published",
                    validated_at=now,
                    published_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                tables["source_catalog_revisions"].insert().values(
                    id=revision_id,
                    source_site=source,
                    sequence=sequence,
                    fingerprint=fingerprint,
                    normalized_payload={"source_site": source, "nodes": []},
                    source_payload={"fixture": True},
                    provenance={"kind": "test"},
                    candidate_id=candidate_id,
                    publication_metadata={"validated": True},
                    published_by="local-operator",
                    published_at=now,
                    created_at=now,
                )
            )
            connection.execute(
                tables["source_catalog_active_revisions"].insert().values(
                    source_site=source,
                    revision_id=revision_id,
                    updated_by="local-operator",
                    updated_at=now,
                )
            )
            catalog_revision_ids[source] = revision_id

        connection.execute(
            tables["scrape_schedules"].insert().values(
                id=automation_id,
                name="Legacy Automation",
                cron_expression="0 9 * * *",
                timezone="Asia/Hong_Kong",
                source_site="jobsdb",
                crawl_phase="detail",
                detail_limit=10,
                revision=1,
                lifecycle_state="active",
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            tables["automation_revisions"].insert().values(
                id=uuid4(),
                automation_id=automation_id,
                revision=1,
                snapshot={"revision": 1},
                snapshot_fingerprint="a" * 64,
                operation="created",
                actor="local-operator",
                created_at=now,
            )
        )
        connection.execute(
            tables["crawl_dispatch_plans"].insert().values(
                id=plan_id,
                state="prepared",
                source_site="jobsdb",
                crawl_phase="detail",
                trigger_kind="saved_automation",
                automation_id=automation_id,
                automation_id_snapshot=automation_id,
                expected_automation_revision=1,
                catalog_revision_id=catalog_revision_ids["jobsdb"],
                authored_scope={"version": 1},
                resolved_scope={"version": 1},
                detail_settings={"version": 1},
                readiness={"ready": True},
                detail_target_count=1,
                plan_fingerprint=plan_fingerprint,
                confirmation_required=False,
                prepared_by="local-operator",
                prepared_at=now,
                expires_at=now + timedelta(minutes=30),
            )
        )
        connection.execute(
            tables["crawl_jobs"].insert().values(
                id=crawl_job_id,
                source_site="jobsdb",
                trigger_type="schedule",
                schedule_id=automation_id,
                dispatch_plan_id=plan_id,
                dispatch_plan_fingerprint=plan_fingerprint,
                status="completed",
                request_payload={"version": 1},
                queued_at=now,
                completed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            tables["crawl_dispatch_plans"]
            .update()
            .where(tables["crawl_dispatch_plans"].c.id == plan_id)
            .values(state="consumed", consumed_at=now, crawl_job_id=crawl_job_id)
        )
        connection.execute(
            tables["crawl_job_listings"].insert().values(
                id=listing_id,
                crawl_job_id=crawl_job_id,
                source_site="jobsdb",
                source_job_id="staged-job",
                source_url="https://example.test/job",
                listing_payload={"id": "staged-job"},
                detail_status="completed",
                detail_attempts=1,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            tables["crawl_dispatch_plan_targets"].insert().values(
                id=target_id,
                plan_id=plan_id,
                source_site="jobsdb",
                source_job_id="staged-job",
                selection_order=0,
                eligibility_fingerprint="b" * 64,
                eligibility_status="eligible",
                status_metadata={},
                created_at=now,
            )
        )
        connection.execute(
            tables["crawl_dispatch_plan_target_rows"].insert().values(
                id=uuid4(),
                plan_target_id=target_id,
                crawl_job_listing_id=listing_id,
                row_order=0,
                eligibility_fingerprint="c" * 64,
                eligibility_status="eligible",
                status_metadata={},
                created_at=now,
            )
        )
        connection.execute(
            tables["crawl_job_events"].insert().values(
                crawl_job_id=crawl_job_id,
                sequence_no=1,
                event_type="crawl.completed",
                payload={},
                created_at=now,
            )
        )
        connection.execute(
            tables["crawl_job_executions"].insert().values(
                id=uuid4(),
                crawl_job_id=crawl_job_id,
                generation=uuid4(),
                launcher_instance_id="test-launcher",
                status="exited",
                command=[],
                exited_at=now,
                exit_code=0,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            tables["crawl_runs"].insert().values(
                id=uuid4(),
                crawl_job_id=crawl_job_id,
                source_site="jobsdb",
                scrapyd_project="test",
                scrapyd_spider="test",
                status="completed",
                pages_processed=1,
                listings_staged=1,
                details_completed=1,
                details_failed=0,
                created_at=now,
                completed_at=now,
            )
        )
        connection.execute(
            tables["schedule_executions"].insert().values(
                id=uuid4(),
                schedule_id=automation_id,
                crawl_job_id=crawl_job_id,
                status="completed",
                started_at=now,
                completed_at=now,
                request_payload_snapshot={"version": 1},
                automation_id_snapshot=automation_id,
                automation_revision=1,
                automation_snapshot={"revision": 1},
                dispatch_plan_id=plan_id,
                dispatch_plan_fingerprint=plan_fingerprint,
                created_at=now,
            )
        )
        connection.execute(
            tables["enrichment_runs"].insert().values(
                id="preserved-enrichment-run",
                source_type="crawl",
                trigger_crawl_job_id=crawl_job_id,
                status="completed",
                job_ids=[str(job_id)],
                total_items=1,
                pending_items=0,
                completed_items=1,
                failed_items=0,
                cancelled_items=0,
                excluded_items=0,
                completed_at=now,
                created_at=now,
            )
        )
        for aggregate_type, event_type, status in (
            ("crawl_job", "crawl.requested", "pending"),
            ("crawl_job", "crawl.requested", "published"),
            ("enrichment_run", "enrichment.run.requested", "pending"),
        ):
            connection.execute(
                tables["event_outbox"].insert().values(
                    topic="crawl.commands" if aggregate_type == "crawl_job" else "enrichment.commands",
                    aggregate_type=aggregate_type,
                    aggregate_id=str(crawl_job_id),
                    event_type=event_type,
                    source_service="test",
                    payload={},
                    status=status,
                    attempt_count=0,
                    available_at=now,
                    published_at=now if status == "published" else None,
                    created_at=now,
                )
            )


def _cutover(engine, **kwargs) -> CrawlControlCutover:
    return CrawlControlCutover(
        engine,
        writer_state_provider=_StoppedWriterStateProvider(),
        **kwargs,
    )


def test_report_hash_excludes_observation_time() -> None:
    first_time = utc_now()
    evidence = tuple(
        WriterStateEvidence(
            writer=writer,
            state="stopped",
            evidence_kind="process",
            evidence_ref=f"test:{writer}:stopped",
            observed_at=first_time,
        )
        for writer in KNOWN_WRITERS
    )
    first = CrawlControlCutoverReport(
        observed_at=first_time,
        schema_revision="20260720_210000",
        backup_id="backup-id",
        backup_acknowledged=True,
        writer_evidence=evidence,
        active_catalog_sources=("ctgoodjobs", "jobsdb", "offertoday"),
        active_crawl_job_count=0,
        reset_counts={},
        preserve_counts={},
        pending_crawl_outbox_count=0,
        preserved_outbox_count=0,
        foreign_keys=(),
        issues=(),
    )
    second = CrawlControlCutoverReport(
        observed_at=first_time + timedelta(minutes=1),
        schema_revision=first.schema_revision,
        backup_id=first.backup_id,
        backup_acknowledged=first.backup_acknowledged,
        writer_evidence=first.writer_evidence,
        active_catalog_sources=first.active_catalog_sources,
        active_crawl_job_count=first.active_crawl_job_count,
        reset_counts=first.reset_counts,
        preserve_counts=first.preserve_counts,
        pending_crawl_outbox_count=first.pending_crawl_outbox_count,
        preserved_outbox_count=first.preserved_outbox_count,
        foreign_keys=first.foreign_keys,
        issues=first.issues,
    )

    assert first.report_hash == second.report_hash


def test_postgres_reset_is_fk_safe_and_preserves_non_control_data(
    postgres_cutover_engine,
) -> None:
    cutover = _cutover(postgres_cutover_engine)
    report = cutover.dry_run(
        backup_id="cp9-rehearsal-backup",
        backup_acknowledged=True,
    )

    assert report.ready, report.issues
    assert report.pending_crawl_outbox_count == 1
    assert report.preserved_outbox_count == 2
    result = cutover.execute(
        backup_id="cp9-rehearsal-backup",
        backup_acknowledged=True,
        expected_report_hash=report.report_hash,
        confirmation=RESET_CONFIRMATION,
    )

    assert result.report_hash == report.report_hash
    with postgres_cutover_engine.connect() as connection:
        for table_name in RESET_TABLES:
            assert connection.scalar(
                select(text("count(*)")).select_from(text(table_name))
            ) == 0
        assert connection.scalar(text("SELECT count(*) FROM companies")) == 1
        assert connection.scalar(text("SELECT count(*) FROM jobs")) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM source_catalog_revisions")
        ) == 3
        assert connection.scalar(text("SELECT count(*) FROM enrichment_runs")) == 1
        assert connection.scalar(
            text(
                "SELECT count(*) FROM enrichment_runs "
                "WHERE trigger_crawl_job_id IS NULL"
            )
        ) == 1
        assert connection.scalar(text("SELECT count(*) FROM event_outbox")) == 2
        assert connection.scalar(
            text("SELECT count(*) FROM event_outbox WHERE status = 'published'")
        ) == 1
        assert connection.scalar(
            text("SELECT count(*) FROM event_outbox WHERE aggregate_type = 'enrichment_run'")
        ) == 1


def test_postgres_failure_injection_rolls_back_the_entire_reset(
    postgres_cutover_engine,
) -> None:
    def fail_after_plans(step, _connection) -> None:
        if step == "crawl_dispatch_plans":
            raise RuntimeError("injected reset failure")

    cutover = _cutover(
        postgres_cutover_engine,
        failure_injector=fail_after_plans,
    )
    report = cutover.dry_run(
        backup_id="cp9-failure-backup",
        backup_acknowledged=True,
    )
    assert report.ready, report.issues

    with pytest.raises(RuntimeError, match="injected reset failure"):
        cutover.execute(
            backup_id="cp9-failure-backup",
            backup_acknowledged=True,
            expected_report_hash=report.report_hash,
            confirmation=RESET_CONFIRMATION,
        )

    with postgres_cutover_engine.connect() as connection:
        for table_name, expected_count in report.reset_counts.items():
            assert connection.scalar(
                text(f'SELECT count(*) FROM "{table_name}"')
            ) == expected_count
        for table_name, expected_count in report.preserve_counts.items():
            assert connection.scalar(
                text(f'SELECT count(*) FROM "{table_name}"')
            ) == expected_count
        assert connection.scalar(text("SELECT count(*) FROM event_outbox")) == 3


def test_postgres_fresh_and_existing_bootstrap_have_schema_parity(
    postgres_cutover_engine,
) -> None:
    def signature() -> dict[str, object]:
        inspector = inspect(postgres_cutover_engine)
        tables = {
            "automation_revisions",
            "crawl_dispatch_plans",
            "crawl_dispatch_plan_targets",
            "crawl_dispatch_plan_target_rows",
            "crawl_job_listings",
            "crawl_jobs",
            "schedule_executions",
            "source_catalog_revisions",
        }
        return {
            table_name: {
                "columns": sorted(
                    (column["name"], str(column["type"]), column["nullable"])
                    for column in inspector.get_columns(table_name)
                ),
                "foreign_keys": sorted(
                    (
                        tuple(item["constrained_columns"]),
                        item["referred_table"],
                        tuple(item["referred_columns"]),
                        (item.get("options") or {}).get("ondelete"),
                    )
                    for item in inspector.get_foreign_keys(table_name)
                ),
                "indexes": sorted(
                    (item["name"], tuple(item["column_names"] or ()), item["unique"])
                    for item in inspector.get_indexes(table_name)
                ),
            }
            for table_name in sorted(tables)
        }

    fresh_metadata_signature = signature()
    _run_alembic(postgres_cutover_engine, "downgrade", "20260720_180000")
    with postgres_cutover_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260720_180000"
        )
    bootstrap_database(db_engine=postgres_cutover_engine, metadata=Base.metadata)
    upgraded_existing_signature = signature()

    assert upgraded_existing_signature == fresh_metadata_signature
    with postgres_cutover_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260720_210000"
        )
        trigger_names = set(
            connection.scalars(
                text(
                    "SELECT tgname FROM pg_trigger "
                    "WHERE NOT tgisinternal AND tgname LIKE 'trg_%'"
                )
            )
        )
    assert {
        "trg_source_catalog_revisions_immutable",
        "trg_automation_revisions_immutable",
        "trg_crawl_dispatch_plans_immutable",
        "trg_crawl_jobs_dispatch_authority_immutable",
    } <= trigger_names


def test_postgres_existing_bootstrap_converges_legacy_orphan_listings(
    postgres_cutover_engine,
) -> None:
    _run_alembic(postgres_cutover_engine, "downgrade", "20260720_180000")
    orphan_listing_id = uuid4()
    with postgres_cutover_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE crawl_job_listings DROP CONSTRAINT "
                "fk_crawl_job_listings_crawl_job_id_crawl_jobs"
            )
        )
        connection.execute(
            Base.metadata.tables["crawl_job_listings"].insert().values(
                id=orphan_listing_id,
                crawl_job_id=uuid4(),
                source_site="offertoday",
                source_job_id="legacy-orphan",
                source_url="https://example.test/legacy-orphan",
                listing_payload={"id": "legacy-orphan"},
                detail_status="pending",
                detail_attempts=0,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )

    _run_alembic(postgres_cutover_engine, "upgrade", "20260720_210000")

    with postgres_cutover_engine.connect() as connection:
        assert connection.scalar(
            text("SELECT count(*) FROM crawl_job_listings WHERE id = :id"),
            {"id": orphan_listing_id},
        ) == 0
        assert connection.scalar(text("SELECT count(*) FROM crawl_job_listings")) == 1
        assert connection.scalar(text("SELECT count(*) FROM companies")) == 1
        assert connection.scalar(text("SELECT count(*) FROM jobs")) == 1
        assert connection.scalar(
            text(
                "SELECT convalidated FROM pg_constraint "
                "WHERE conname = "
                "'fk_crawl_job_listings_crawl_job_id_crawl_jobs'"
            )
        ) is True
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
            "20260720_210000"
        )
