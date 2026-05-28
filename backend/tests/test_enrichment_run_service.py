from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.company import Company
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job
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
            Company.__table__,
            Job.__table__,
            EnrichmentRun.__table__,
            EnrichmentRunItem.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
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
            _FakeQuery(one_result=(400, 4)),
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
    assert overview["running_runs"] == 0
    assert overview["active_runs"] == 1
    assert overview["failed_items"] == 0
    assert overview["failed_jobs"] == 0


def test_get_overview_scans_failed_jobs_when_failed_items_exist(monkeypatch):
    db = _FakeDB(
        [
            _FakeQuery(one_result=(400, 4)),
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
    assert overview["running_runs"] == 0
    assert overview["active_runs"] == 1
    assert overview["failed_items"] == 3
    assert overview["failed_jobs"] == 2
    assert failed_job_scan_calls == [True]


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
