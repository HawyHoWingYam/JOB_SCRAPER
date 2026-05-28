from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.api import ai
from app.database import Base
from app.models.company import Company
from app.models.enrichment_run import EnrichmentRun, EnrichmentRunItem
from app.models.job import Job


def _build_run(*, run_id: str = "run-1", status: str, failed_items: int):
    return SimpleNamespace(
        id=run_id,
        source_type="manual_pending",
        trigger_crawl_job_id=uuid4(),
        status=status,
        job_ids=[],
        total_items=4,
        pending_items=1,
        completed_items=3,
        failed_items=failed_items,
        started_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
        completed_at=datetime(2026, 5, 28, 9, 5, tzinfo=UTC),
        created_at=datetime(2026, 5, 28, 8, 59, tzinfo=UTC),
        current_job_title="Title A",
        error_message=None,
    )


def test_serialize_run_skips_failed_title_lookup_when_run_has_no_failed_items(monkeypatch):
    run = _build_run(status="completed", failed_items=0)

    def fail_lookup(db, run_id):
        raise AssertionError("last failed title lookup should be skipped for non-failed runs")

    monkeypatch.setattr(ai, "_derive_last_failed_job_title", fail_lookup)

    payload = ai._serialize_run(run, db=object())

    assert payload["last_failed_job_title"] is None


def test_serialize_run_looks_up_failed_title_when_failed_items_exist(monkeypatch):
    run = _build_run(status="completed_with_failures", failed_items=2)

    def resolve_lookup(db, run_id):
        assert run_id == run.id
        return "Platform Analyst"

    monkeypatch.setattr(ai, "_derive_last_failed_job_title", resolve_lookup)

    payload = ai._serialize_run(run, db=object())

    assert payload["last_failed_job_title"] == "Platform Analyst"


def test_serialize_run_uses_precomputed_failed_title_map_without_lookup(monkeypatch):
    run = _build_run(status="completed_with_failures", failed_items=2)

    def fail_lookup(db, run_id):
        raise AssertionError("single-run failed title lookup should be skipped when a precomputed map is provided")

    monkeypatch.setattr(ai, "_derive_last_failed_job_title", fail_lookup)

    payload = ai._serialize_run(
        run,
        db=object(),
        last_failed_job_titles={run.id: "Platform Analyst"},
    )

    assert payload["last_failed_job_title"] == "Platform Analyst"


def test_derive_last_failed_job_titles_resolves_latest_title_per_run_with_single_select():
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

    latest_job_id = uuid4()
    older_job_id = uuid4()
    other_run_job_id = uuid4()
    db.add_all(
        [
            Job(
                id=latest_job_id,
                job_id="job-latest",
                source_site="jobsdb",
                source_job_id="job-latest",
                company_id=company_id,
                title="Latest Failed Title",
            ),
            Job(
                id=older_job_id,
                job_id="job-older",
                source_site="jobsdb",
                source_job_id="job-older",
                company_id=company_id,
                title="Older Failed Title",
            ),
            Job(
                id=other_run_job_id,
                job_id="job-other-run",
                source_site="jobsdb",
                source_job_id="job-other-run",
                company_id=company_id,
                title="Other Run Failed Title",
            ),
        ]
    )
    db.add_all(
        [
            EnrichmentRun(
                id="run-1",
                source_type="manual_pending",
                status="completed_with_failures",
                job_ids=[],
                total_items=2,
                pending_items=0,
                completed_items=0,
                failed_items=2,
                created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
                started_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
                completed_at=datetime(2026, 5, 28, 9, 10, tzinfo=UTC),
            ),
            EnrichmentRun(
                id="run-2",
                source_type="manual_pending",
                status="failed",
                job_ids=[],
                total_items=1,
                pending_items=0,
                completed_items=0,
                failed_items=1,
                created_at=datetime(2026, 5, 28, 8, 0, tzinfo=UTC),
                started_at=datetime(2026, 5, 28, 8, 0, tzinfo=UTC),
                completed_at=datetime(2026, 5, 28, 8, 2, tzinfo=UTC),
            ),
        ]
    )
    db.add_all(
        [
            EnrichmentRunItem(
                id="item-run-1-older",
                run_id="run-1",
                job_id=older_job_id,
                position=0,
                status="failed",
                started_at=datetime(2026, 5, 28, 9, 1, tzinfo=UTC),
                completed_at=datetime(2026, 5, 28, 9, 5, tzinfo=UTC),
                created_at=datetime(2026, 5, 28, 9, 1, tzinfo=UTC),
            ),
            EnrichmentRunItem(
                id="item-run-1-latest",
                run_id="run-1",
                job_id=latest_job_id,
                position=1,
                status="failed",
                started_at=datetime(2026, 5, 28, 9, 6, tzinfo=UTC),
                completed_at=datetime(2026, 5, 28, 9, 10, tzinfo=UTC),
                created_at=datetime(2026, 5, 28, 9, 6, tzinfo=UTC),
            ),
            EnrichmentRunItem(
                id="item-run-2-only",
                run_id="run-2",
                job_id=other_run_job_id,
                position=0,
                status="failed",
                started_at=datetime(2026, 5, 28, 8, 1, tzinfo=UTC),
                completed_at=datetime(2026, 5, 28, 8, 2, tzinfo=UTC),
                created_at=datetime(2026, 5, 28, 8, 1, tzinfo=UTC),
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
        payload = ai._derive_last_failed_job_titles(db, ["run-1", "run-2"])
    finally:
        event.remove(engine, "before_cursor_execute", _count_selects)
        db.close()

    assert payload == {
        "run-1": "Latest Failed Title",
        "run-2": "Other Run Failed Title",
    }
    assert len(select_statements) == 1


def test_list_enrichment_runs_batches_failed_title_lookup_for_failed_runs(monkeypatch):
    failed_run = _build_run(run_id="run-failed", status="completed_with_failures", failed_items=2)
    completed_run = _build_run(run_id="run-completed", status="completed", failed_items=0)
    batch_calls = []

    class _FakeService:
        def __init__(self, db):
            self.db = db

        def list_runs_for_monitor(self):
            return [failed_run, completed_run]

        def list_runs(self, status=None, source_type=None, limit=None):
            return [failed_run, completed_run]

    def resolve_batch_lookup(db, run_ids):
        batch_calls.append(list(run_ids))
        return {"run-failed": "Platform Analyst"}

    def fail_single_lookup(db, run_id):
        raise AssertionError("list_enrichment_runs should use the batch failed-title lookup")

    monkeypatch.setattr(ai, "EnrichmentRunService", _FakeService)
    monkeypatch.setattr(ai, "_derive_last_failed_job_titles", resolve_batch_lookup)
    monkeypatch.setattr(ai, "_derive_last_failed_job_title", fail_single_lookup)

    payload = asyncio.run(ai.list_enrichment_runs(db=object()))

    assert batch_calls == [["run-failed"]]
    assert payload["runs"][0]["last_failed_job_title"] == "Platform Analyst"
    assert payload["runs"][1]["last_failed_job_title"] is None
