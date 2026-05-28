from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.company import Company
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.event_outbox import EventOutbox
from app.models.job import Job
from app.models.schedule import ScheduleExecution, ScrapeSchedule
from app.services.enrichment_run_service import EnrichmentRunService


class _FakeQuery:
    def __init__(self, *, count_result=None, first_result=None, one_result=None):
        self.count_result = count_result
        self.first_result = first_result
        self.one_result = one_result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def one(self):
        return self.one_result

    def count(self):
        return self.count_result

    def first(self):
        return self.first_result


class _FakeDB:
    def __init__(self, queries):
        self._queries = list(queries)
        self.query_calls = []

    def query(self, *entities):
        self.query_calls.append(entities)
        if not self._queries:
            raise AssertionError("Unexpected query call")
        return self._queries.pop(0)


def _create_enrichment_run_service_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
            Company.__table__,
            EventOutbox.__table__,
            Job.__table__,
            ScheduleExecution.__table__,
            EnrichmentRun.__table__,
            EnrichmentRunItem.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=True, autocommit=False)
    db = session_factory()

    company_id = uuid4()
    db.add(
        Company(
            id=company_id,
            company_id="company-1",
            source_site="jobsdb",
            source_company_id="company-1",
            name="Example Co",
        )
    )
    job_ids = [uuid4(), uuid4(), uuid4()]
    db.add_all(
        [
            Job(
                id=job_ids[0],
                job_id="job-1",
                source_site="jobsdb",
                source_job_id="job-1",
                company_id=company_id,
                title="Job 1",
            ),
            Job(
                id=job_ids[1],
                job_id="job-2",
                source_site="jobsdb",
                source_job_id="job-2",
                company_id=company_id,
                title="Job 2",
            ),
            Job(
                id=job_ids[2],
                job_id="job-3",
                source_site="jobsdb",
                source_job_id="job-3",
                company_id=company_id,
                title="Job 3",
            ),
        ]
    )
    db.commit()
    return engine, db, job_ids


def test_get_overview_skips_failed_job_scan_when_failed_item_count_is_zero(monkeypatch):
    db = _FakeDB(
        [
            _FakeQuery(one_result=(400, 4, 4, 396)),
            _FakeQuery(one_result=(0, 1)),
            _FakeQuery(count_result=0),
            _FakeQuery(first_result=None),
        ]
    )
    service = EnrichmentRunService(db)

    def fail_failed_job_scan():
        raise AssertionError("failed job scan should be skipped when there are no failed items")

    monkeypatch.setattr(service, "_count_current_failed_jobs", fail_failed_job_scan)

    overview = service.get_overview()

    assert overview["total_jobs"] == 400
    assert overview["enriched_jobs"] == 4
    assert overview["pending_jobs"] == 396
    assert overview["running_runs"] == 0
    assert overview["active_runs"] == 1
    assert overview["failed_items"] == 0
    assert overview["failed_jobs"] == 0


def test_get_overview_scans_failed_jobs_when_failed_items_exist(monkeypatch):
    db = _FakeDB(
        [
            _FakeQuery(one_result=(400, 4, 4, 396)),
            _FakeQuery(one_result=(0, 1)),
            _FakeQuery(count_result=3),
            _FakeQuery(first_result=None),
        ]
    )
    service = EnrichmentRunService(db)
    failed_job_scan_calls = []

    def resolve_failed_job_scan():
        failed_job_scan_calls.append(True)
        return 2

    monkeypatch.setattr(service, "_count_current_failed_jobs", resolve_failed_job_scan)

    overview = service.get_overview()

    assert overview["total_jobs"] == 400
    assert overview["enriched_jobs"] == 4
    assert overview["pending_jobs"] == 396
    assert overview["running_runs"] == 0
    assert overview["active_runs"] == 1
    assert overview["failed_items"] == 3
    assert overview["failed_jobs"] == 2
    assert failed_job_scan_calls == [True]


def test_get_overview_counts_only_ai_eligible_unenriched_jobs_as_pending():
    _engine, db, job_ids = _create_enrichment_run_service_db()
    now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    jobs = db.query(Job).order_by(Job.job_id.asc()).all()

    eligible_pending_job = jobs[0]
    eligible_pending_job.source_classification_id = "it"
    eligible_pending_job.source_classification_name = "Information Technology"

    already_enriched_job = jobs[1]
    already_enriched_job.source_classification_id = "it"
    already_enriched_job.source_classification_name = "Information Technology"
    already_enriched_job.ai_enriched_at = now

    ineligible_pending_job = jobs[2]
    ineligible_pending_job.source_classification_id = None
    ineligible_pending_job.source_classification_name = None

    db.commit()

    overview = EnrichmentRunService(db).get_overview()

    assert overview["total_jobs"] == 3
    assert overview["enriched_jobs"] == 1
    assert overview["ai_eligible_jobs"] == 2
    assert overview["ineligible_jobs"] == 1
    assert overview["pending_jobs"] == 1
    db.close()


def test_get_overview_keeps_ineligible_enriched_jobs_out_of_eligible_cohort_counts():
    _engine, db, job_ids = _create_enrichment_run_service_db()
    now = datetime(2026, 5, 28, 12, 0, tzinfo=UTC)
    jobs = db.query(Job).order_by(Job.job_id.asc()).all()

    eligible_pending_job = jobs[0]
    eligible_pending_job.source_classification_id = "it"
    eligible_pending_job.source_classification_name = "Information Technology"

    eligible_enriched_job = jobs[1]
    eligible_enriched_job.source_classification_id = "it"
    eligible_enriched_job.source_classification_name = "Information Technology"
    eligible_enriched_job.ai_enriched_at = now

    ineligible_enriched_job = jobs[2]
    ineligible_enriched_job.source_classification_id = None
    ineligible_enriched_job.source_classification_name = None
    ineligible_enriched_job.ai_enriched_at = now

    db.commit()

    queue_counts = EnrichmentRunService(db).get_job_queue_counts()

    assert queue_counts == {
        "total_jobs": 3,
        "enriched_jobs": 2,
        "eligible_enriched_jobs": 1,
        "ai_eligible_jobs": 2,
        "ineligible_jobs": 1,
        "pending_jobs": 1,
    }
    db.close()


def test_list_runs_for_monitor_selects_active_pair_with_single_select():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[EnrichmentRun.__table__],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()

    db.add_all(
        [
            EnrichmentRun(
                id="run-completed-latest",
                source_type="manual_pending",
                status="completed",
                job_ids=[],
                total_items=3,
                pending_items=0,
                completed_items=3,
                failed_items=0,
                created_at=datetime(2026, 4, 15, 12, 0, tzinfo=UTC),
                started_at=datetime(2026, 4, 15, 12, 0, tzinfo=UTC),
                completed_at=datetime(2026, 4, 15, 12, 3, tzinfo=UTC),
            ),
            EnrichmentRun(
                id="run-failed-visible",
                source_type="post_scrape",
                status="completed_with_failures",
                job_ids=[],
                total_items=4,
                pending_items=0,
                completed_items=2,
                failed_items=2,
                created_at=datetime(2026, 4, 15, 11, 0, tzinfo=UTC),
                started_at=datetime(2026, 4, 15, 11, 0, tzinfo=UTC),
                completed_at=datetime(2026, 4, 15, 11, 8, tzinfo=UTC),
            ),
            EnrichmentRun(
                id="run-active-newest",
                source_type="post_scrape",
                status="running",
                job_ids=[],
                total_items=4,
                pending_items=3,
                completed_items=1,
                failed_items=0,
                created_at=datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
                started_at=datetime(2026, 4, 15, 10, 0, tzinfo=UTC),
            ),
            EnrichmentRun(
                id="run-active-older",
                source_type="manual_pending",
                status="pending",
                job_ids=[],
                total_items=2,
                pending_items=2,
                completed_items=0,
                failed_items=0,
                created_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
                started_at=datetime(2026, 4, 15, 9, 0, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    select_statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _count_selects(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    try:
        runs = EnrichmentRunService(db).list_runs_for_monitor()
    finally:
        event.remove(engine, "before_cursor_execute", _count_selects)
        db.close()

    assert [run.id for run in runs] == ["run-failed-visible", "run-active-newest"]
    assert len(select_statements) == 1


def test_list_run_items_or_none_distinguishes_missing_empty_and_filtered_runs_with_single_select():
    engine, db, job_ids = _create_enrichment_run_service_db()
    db.add_all(
        [
            EnrichmentRun(
                id="run-empty",
                source_type="manual_pending",
                status="completed",
                job_ids=[],
                total_items=0,
                pending_items=0,
                completed_items=0,
                failed_items=0,
                created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
            ),
            EnrichmentRun(
                id="run-with-items",
                source_type="manual_pending",
                status="completed_with_failures",
                job_ids=[],
                total_items=2,
                pending_items=0,
                completed_items=1,
                failed_items=1,
                created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
            ),
        ]
    )
    db.add_all(
        [
            EnrichmentRunItem(
                id="item-completed",
                run_id="run-with-items",
                job_id=job_ids[0],
                position=0,
                status="completed",
                created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
            ),
            EnrichmentRunItem(
                id="item-failed",
                run_id="run-with-items",
                job_id=job_ids[1],
                position=1,
                status="failed",
                created_at=datetime(2026, 5, 28, 9, 1, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    select_statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _count_selects(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    try:
        service = EnrichmentRunService(db)
        missing_items = service.list_run_items_or_none("run-missing")
        empty_items = service.list_run_items_or_none("run-empty")
        failed_items = service.list_run_items_or_none("run-with-items", status="failed")
    finally:
        event.remove(engine, "before_cursor_execute", _count_selects)
        db.close()

    assert missing_items is None
    assert empty_items == []
    assert [item.id for item in failed_items] == ["item-failed"]
    assert len(select_statements) == 3


def test_create_retry_run_from_failed_items_preserves_404_and_400_semantics_with_single_select():
    engine, db, job_ids = _create_enrichment_run_service_db()
    db.add_all(
        [
            EnrichmentRun(
                id="run-no-failed",
                source_type="manual_pending",
                status="completed",
                job_ids=[],
                total_items=1,
                pending_items=0,
                completed_items=1,
                failed_items=0,
                created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
            ),
            EnrichmentRun(
                id="run-with-failed",
                source_type="manual_pending",
                status="completed_with_failures",
                job_ids=[],
                total_items=2,
                pending_items=0,
                completed_items=1,
                failed_items=1,
                created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
            ),
        ]
    )
    db.add_all(
        [
            EnrichmentRunItem(
                id="item-success",
                run_id="run-no-failed",
                job_id=job_ids[0],
                position=0,
                status="completed",
                created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
            ),
            EnrichmentRunItem(
                id="item-run-with-failed-success",
                run_id="run-with-failed",
                job_id=job_ids[1],
                position=0,
                status="completed",
                created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
            ),
            EnrichmentRunItem(
                id="item-run-with-failed-failed",
                run_id="run-with-failed",
                job_id=job_ids[2],
                position=1,
                status="failed",
                created_at=datetime(2026, 5, 28, 9, 1, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    created_runs = []
    select_statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _count_selects(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            select_statements.append(statement)

    try:
        service = EnrichmentRunService(db)

        def _capture_create_run(*, source_type, job_ids):
            created_runs.append((source_type, list(job_ids)))
            return SimpleNamespace(id="retry-run")

        service._create_run = _capture_create_run

        missing_run = service.create_retry_run_from_failed_items("run-missing")
        with pytest.raises(ValueError, match="Run run-no-failed has no failed items to retry"):
            service.create_retry_run_from_failed_items("run-no-failed")
        created_run = service.create_retry_run_from_failed_items("run-with-failed")
    finally:
        event.remove(engine, "before_cursor_execute", _count_selects)
        db.close()

    assert missing_run is None
    assert created_run.id == "retry-run"
    assert created_runs == [("retry_failed", [str(job_ids[2])])]
    assert len(select_statements) == 3


def test_execute_run_updates_linked_crawl_job_ai_metrics_and_schedule_phase5():
    engine, db, job_ids = _create_enrichment_run_service_db()
    schedule_id = uuid4()
    crawl_job_id = uuid4()
    db.add(
        ScrapeSchedule(
            id=schedule_id,
            name="JobsDB Nightly",
            cron_expression="0 2 * * *",
            source_site="jobsdb",
            crawl_phase="listing",
            crawl_mode="headed",
            category_ids=[1200],
            is_active=True,
        )
    )
    db.add(
        CrawlJob(
            id=crawl_job_id,
            source_site="jobsdb",
            trigger_type="schedule",
            schedule_id=schedule_id,
            status="completed",
            request_payload={"crawl_phase": "listing", "source_site": "jobsdb"},
            requested_by="tester",
            queued_at=datetime(2026, 5, 28, 8, 55, tzinfo=UTC),
            started_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
            completed_at=datetime(2026, 5, 28, 9, 1, tzinfo=UTC),
            metrics={},
        )
    )
    db.add(
        ScheduleExecution(
            id=uuid4(),
            schedule_id=schedule_id,
            crawl_job_id=crawl_job_id,
            status="running",
            started_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
        )
    )
    db.add(
        EnrichmentRun(
            id="run-linked-ai",
            source_type="crawl_auto",
            trigger_crawl_job_id=crawl_job_id,
            status="pending",
            job_ids=[str(job_ids[0]), str(job_ids[1])],
            total_items=2,
            pending_items=2,
            completed_items=0,
            failed_items=0,
            created_at=datetime(2026, 5, 28, 9, 2, tzinfo=UTC),
            started_at=None,
            completed_at=None,
        )
    )
    db.add_all(
        [
            EnrichmentRunItem(
                id="linked-item-1",
                run_id="run-linked-ai",
                job_id=job_ids[0],
                position=0,
                status="pending",
                created_at=datetime(2026, 5, 28, 9, 2, tzinfo=UTC),
            ),
            EnrichmentRunItem(
                id="linked-item-2",
                run_id="run-linked-ai",
                job_id=job_ids[1],
                position=1,
                status="pending",
                created_at=datetime(2026, 5, 28, 9, 3, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    class _FakeEnrichmentService:
        async def enrich_job_id(self, job_id):
            return {"job_id": str(job_id), "status": "success"}

    service = EnrichmentRunService(db)
    service._resolve_run_concurrency = lambda: 1
    service._enqueue_job_enriched_event = lambda **kwargs: None

    run = asyncio.run(
        service.execute_run(
            "run-linked-ai",
            enrichment_service=_FakeEnrichmentService(),
            claim=False,
        )
    )

    refreshed_crawl_job = db.query(CrawlJob).filter(CrawlJob.id == crawl_job_id).one()
    refreshed_execution = db.query(ScheduleExecution).filter(ScheduleExecution.crawl_job_id == crawl_job_id).one()

    assert run.status == "completed"
    assert refreshed_crawl_job.metrics["ai_run_id"] == "run-linked-ai"
    assert refreshed_crawl_job.metrics["ai_total_items"] == 2
    assert refreshed_crawl_job.metrics["ai_completed_items"] == 2
    assert refreshed_crawl_job.metrics["ai_failed_items"] == 0
    assert refreshed_execution.phase5_completed is True
    db.close()


def test_request_crawl_auto_run_if_ready_uses_persisted_run_items_when_ingest_metric_lags(monkeypatch):
    _engine, db, job_ids = _create_enrichment_run_service_db()
    crawl_job_id = uuid4()
    db.add(
        CrawlJob(
            id=crawl_job_id,
            source_site="jobsdb",
            trigger_type="manual",
            status="completed",
            request_payload={"crawl_phase": "detail", "source_site": "jobsdb"},
            requested_by="tester",
            queued_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
            started_at=datetime(2026, 5, 28, 10, 1, tzinfo=UTC),
            completed_at=datetime(2026, 5, 28, 10, 2, tzinfo=UTC),
            metrics={
                "items_emitted": 2,
                "ingest_items_seen": 1,
            },
        )
    )
    db.add(
        EnrichmentRun(
            id="run-crawl-auto-pending",
            source_type="crawl_auto",
            trigger_crawl_job_id=crawl_job_id,
            status="pending",
            job_ids=[str(job_ids[0]), str(job_ids[1])],
            total_items=2,
            pending_items=2,
            completed_items=0,
            failed_items=0,
            created_at=datetime(2026, 5, 28, 10, 3, tzinfo=UTC),
        )
    )
    db.commit()

    class _FakeRuntimeSettingsService:
        def __init__(self, db):
            self.db = db

        def get_profile_runtime_metadata(self, _scope):
            return SimpleNamespace(is_ready=True)

    requested_runs = []
    service = EnrichmentRunService(db)
    monkeypatch.setattr(
        "app.services.enrichment_run_service.AIRuntimeSettingsService",
        _FakeRuntimeSettingsService,
    )
    monkeypatch.setattr(
        service,
        "request_run_execution",
        lambda run_id, *, source_service="ai-api": requested_runs.append((run_id, source_service)) or True,
    )

    assert service.request_crawl_auto_run_if_ready(str(crawl_job_id)) is True
    assert requested_runs == [("run-crawl-auto-pending", "enrichment-worker")]
    db.close()


def test_describe_pending_gate_reports_ingest_settle_blocker_for_crawl_auto_runs(monkeypatch):
    _engine, db, job_ids = _create_enrichment_run_service_db()
    crawl_job_id = uuid4()
    run = EnrichmentRun(
        id="run-crawl-auto-gated",
        source_type="crawl_auto",
        trigger_crawl_job_id=crawl_job_id,
        status="pending",
        job_ids=[str(job_ids[0])],
        total_items=1,
        pending_items=1,
        completed_items=0,
        failed_items=0,
        created_at=datetime(2026, 5, 28, 10, 3, tzinfo=UTC),
    )
    db.add(
        CrawlJob(
            id=crawl_job_id,
            source_site="jobsdb",
            trigger_type="manual",
            status="completed",
            request_payload={"crawl_phase": "detail", "source_site": "jobsdb"},
            requested_by="tester",
            queued_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
            started_at=datetime(2026, 5, 28, 10, 1, tzinfo=UTC),
            completed_at=datetime(2026, 5, 28, 10, 2, tzinfo=UTC),
            metrics={
                "items_emitted": 10,
                "ingest_items_seen": 2,
                "ingest_items_failed": 6,
                "ingest_dead_lettered": 6,
            },
        )
    )
    db.add(run)
    db.commit()

    class _FakeRuntimeSettingsService:
        def __init__(self, db):
            self.db = db

        def get_profile_runtime_metadata(self, _scope):
            return SimpleNamespace(is_ready=True)

    monkeypatch.setattr(
        "app.services.enrichment_run_service.AIRuntimeSettingsService",
        _FakeRuntimeSettingsService,
    )

    gate = EnrichmentRunService(db).describe_pending_gate(run)

    assert gate == {
        "reason": "waiting_for_ingest_settle",
        "emitted_items": 10,
        "settled_items": 8,
        "crawl_job_status": "completed",
    }
    db.close()


def test_describe_pending_gate_reports_manual_runs_as_queued_for_execution():
    _engine, db, job_ids = _create_enrichment_run_service_db()
    run = EnrichmentRun(
        id="run-manual-pending",
        source_type="manual_pending",
        status="pending",
        job_ids=[str(job_ids[0])],
        total_items=1,
        pending_items=1,
        completed_items=0,
        failed_items=0,
        created_at=datetime(2026, 5, 28, 10, 3, tzinfo=UTC),
    )
    db.add(run)
    db.commit()

    gate = EnrichmentRunService(db).describe_pending_gate(run)

    assert gate == {
        "reason": "queued_for_execution",
    }
    db.close()


def test_describe_pending_gate_uses_durable_settled_event_count_when_it_exceeds_metrics(monkeypatch):
    _engine, db, job_ids = _create_enrichment_run_service_db()
    crawl_job_id = uuid4()
    run = EnrichmentRun(
        id="run-crawl-auto-events-win",
        source_type="crawl_auto",
        trigger_crawl_job_id=crawl_job_id,
        status="pending",
        job_ids=[str(job_ids[0])],
        total_items=1,
        pending_items=1,
        completed_items=0,
        failed_items=0,
        created_at=datetime(2026, 5, 28, 10, 3, tzinfo=UTC),
    )
    db.add(
        CrawlJob(
            id=crawl_job_id,
            source_site="jobsdb",
            trigger_type="manual",
            status="completed",
            request_payload={"crawl_phase": "detail", "source_site": "jobsdb"},
            requested_by="tester",
            queued_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
            started_at=datetime(2026, 5, 28, 10, 1, tzinfo=UTC),
            completed_at=datetime(2026, 5, 28, 10, 2, tzinfo=UTC),
            metrics={
                "items_emitted": 100,
                "ingest_items_seen": 30,
                "ingest_items_failed": 68,
                "ingest_dead_lettered": 68,
            },
        )
    )
    db.add(run)
    db.commit()

    class _FakeRuntimeSettingsService:
        def __init__(self, db):
            self.db = db

        def get_profile_runtime_metadata(self, _scope):
            return SimpleNamespace(is_ready=True)

    service = EnrichmentRunService(db)
    monkeypatch.setattr(
        "app.services.enrichment_run_service.AIRuntimeSettingsService",
        _FakeRuntimeSettingsService,
    )
    monkeypatch.setattr(
        service.crawl_job_repository,
        "count_events",
        lambda db, crawl_job_id, event_types=None: 100,
    )

    gate = service.describe_pending_gate(run)

    assert gate == {
        "reason": "queued_for_execution",
    }
    db.close()


def test_request_ready_pending_runs_enqueues_only_runs_that_are_ready_to_execute(monkeypatch):
    _engine, db, job_ids = _create_enrichment_run_service_db()
    ready_run = EnrichmentRun(
        id="run-ready-pending",
        source_type="manual_pending",
        status="pending",
        job_ids=[str(job_ids[0])],
        total_items=1,
        pending_items=1,
        completed_items=0,
        failed_items=0,
        created_at=datetime(2026, 5, 28, 10, 0, tzinfo=UTC),
    )
    blocked_run = EnrichmentRun(
        id="run-blocked-pending",
        source_type="crawl_auto",
        status="pending",
        job_ids=[str(job_ids[1])],
        total_items=1,
        pending_items=1,
        completed_items=0,
        failed_items=0,
        created_at=datetime(2026, 5, 28, 10, 1, tzinfo=UTC),
    )
    db.add_all([ready_run, blocked_run])
    db.commit()

    service = EnrichmentRunService(db)
    original_describe_pending_gate = service.describe_pending_gate

    def _describe_pending_gate(run, *, crawl_job=None):
        if run.id == "run-blocked-pending":
            return {"reason": "waiting_for_ingest_settle"}
        return original_describe_pending_gate(run, crawl_job=crawl_job)

    monkeypatch.setattr(service, "describe_pending_gate", _describe_pending_gate)

    requested_count = service.request_ready_pending_runs(source_service="enrichment-worker-startup")
    db.commit()

    outbox_rows = (
        db.query(EventOutbox)
        .filter(EventOutbox.aggregate_type == "enrichment_run")
        .order_by(EventOutbox.id.asc())
        .all()
    )

    assert requested_count == 1
    assert len(outbox_rows) == 1
    assert outbox_rows[0].aggregate_id == "run-ready-pending"
    assert outbox_rows[0].event_type == "enrichment.run.requested"
    db.close()
