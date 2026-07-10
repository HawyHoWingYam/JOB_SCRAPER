from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.company import Company
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_listing import CrawlJobListing
from app.models.crawl_run import CrawlRun
from app.models.job import Job
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.services.startup_recovery_service import (
    CRAWL_JOB_RESTART_MESSAGE,
    StartupRecoveryService,
)


_STARTED_AT = datetime(2026, 7, 10, 9, 0, tzinfo=UTC)


def _uuid(value: int) -> UUID:
    return UUID(f"aaaaaaaa-aaaa-aaaa-aaaa-{value:012x}")


def _build_session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(
        engine,
        tables=[
            Company.__table__,
            Job.__table__,
            CrawlJob.__table__,
            CrawlRun.__table__,
            CrawlJobEvent.__table__,
            CrawlJobListing.__table__,
        ],
    )
    return Session(engine)


def _company(*, row_id: int = 1) -> Company:
    return Company(
        id=_uuid(row_id),
        company_id=f"offertoday:company-{row_id}",
        source_site="offertoday",
        source_company_id=f"company-{row_id}",
        name=f"Company {row_id}",
    )


def _published_job(
    source_job_id: str,
    *,
    company_id: UUID,
    row_id: int,
    description: str = "Complete OfferToday description",
) -> Job:
    return Job(
        id=_uuid(row_id),
        job_id=f"offertoday:{source_job_id}",
        source_site="offertoday",
        source_job_id=source_job_id,
        company_id=company_id,
        title=f"OfferToday job {source_job_id}",
        description=description,
        raw_data={
            "jobId": source_job_id,
            "jobDesc": description,
            "recovered": True,
        },
        is_deleted=False,
    )


def _crawl_job(*, row_id: int, source_site: str = "offertoday") -> CrawlJob:
    return CrawlJob(
        id=_uuid(row_id),
        source_site=source_site,
        trigger_type="manual",
        status="running",
        request_payload={"crawl_phase": "detail"},
        requested_by="pytest",
        started_at=_STARTED_AT + timedelta(seconds=row_id),
        created_at=_STARTED_AT + timedelta(seconds=row_id),
    )


def _running_listing(
    *,
    row_id: int,
    detail_crawl_job_id: UUID,
    source_site: str,
    source_job_id: str,
) -> CrawlJobListing:
    return CrawlJobListing(
        id=_uuid(row_id),
        crawl_job_id=_uuid(10_000 + row_id),
        source_site=source_site,
        source_job_id=source_job_id,
        source_url=f"https://example.test/{source_site}/{source_job_id}",
        listing_payload={"jobId": source_job_id},
        detail_payload={"stale": True},
        detail_status="running",
        detail_attempts=1,
        last_detail_crawl_job_id=detail_crawl_job_id,
        detail_error_message="stale error",
        detail_started_at=_STARTED_AT,
        created_at=_STARTED_AT + timedelta(seconds=row_id),
        updated_at=_STARTED_AT + timedelta(seconds=row_id),
    )


def _recover_crawls(db: Session) -> dict[str, int]:
    return StartupRecoveryService(db).recover_interrupted_operations(
        recover_ai_runs=False,
        recover_company_runs=False,
        recover_crawl_jobs=True,
        recover_schedule_executions=False,
    )


def test_complete_offertoday_running_detail_reconciles_existing_job_and_records_event():
    db = _build_session()
    try:
        company = _company()
        crawl_job = _crawl_job(row_id=101)
        job = _published_job(
            "shared-1",
            company_id=company.id,
            row_id=201,
        )
        listing = _running_listing(
            row_id=301,
            detail_crawl_job_id=crawl_job.id,
            source_site="offertoday",
            source_job_id="shared-1",
        )
        db.add_all([company, crawl_job, job, listing])
        db.commit()

        summary = _recover_crawls(db)
        db.refresh(crawl_job)
        db.refresh(listing)

        assert summary["crawl_jobs_recovered"] == 1
        assert crawl_job.status == "failed"
        assert crawl_job.error_message == CRAWL_JOB_RESTART_MESSAGE
        assert listing.detail_status == "completed"
        assert listing.published_job_id == job.id
        assert listing.detail_payload == job.raw_data
        assert listing.detail_error_message is None
        assert listing.detail_completed_at is not None

        event = db.query(CrawlJobEvent).one()
        assert event.crawl_job_id == crawl_job.id
        assert event.event_type == "crawl.detail_recovered"
        assert event.emitted_by == "startup-recovery"
        assert event.payload == {
            "records": [
                {
                    "listing_id": str(listing.id),
                    "source_site": "offertoday",
                    "source_job_id": "shared-1",
                    "before_status": "running",
                    "after_status": "completed",
                    "outcome": "reconciled_existing_job",
                    "published_job_id": str(job.id),
                    "counts_as_fetch_success": False,
                }
            ]
        }
        assert db.query(CrawlJobEvent).filter(
            CrawlJobEvent.event_type == "crawl.detail_persisted"
        ).count() == 0
        assert db.query(CrawlJobListing).filter(
            CrawlJobListing.last_detail_crawl_job_id == crawl_job.id,
            CrawlJobListing.detail_status == "running",
        ).count() == 0
    finally:
        db.close()


def test_complete_offertoday_job_without_raw_data_recovers_an_empty_detail_payload():
    db = _build_session()
    try:
        company = _company()
        crawl_job = _crawl_job(row_id=106)
        job = _published_job(
            "no-raw-data",
            company_id=company.id,
            row_id=206,
        )
        job.raw_data = None
        listing = _running_listing(
            row_id=310,
            detail_crawl_job_id=crawl_job.id,
            source_site="offertoday",
            source_job_id="no-raw-data",
        )
        db.add_all([company, crawl_job, job, listing])
        db.commit()

        _recover_crawls(db)
        db.refresh(listing)

        assert listing.detail_status == "completed"
        assert listing.detail_payload == {}
        assert listing.published_job_id == job.id
    finally:
        db.close()


def test_incomplete_missing_and_other_source_running_details_fail_without_cross_linking():
    db = _build_session()
    try:
        company = _company()
        crawl_job = _crawl_job(row_id=102)
        complete_shared_job = _published_job(
            "same-id",
            company_id=company.id,
            row_id=202,
        )
        incomplete_job = _published_job(
            "partial",
            company_id=company.id,
            row_id=203,
            description="",
        )
        rows = [
            _running_listing(
                row_id=302,
                detail_crawl_job_id=crawl_job.id,
                source_site="offertoday",
                source_job_id="partial",
            ),
            _running_listing(
                row_id=303,
                detail_crawl_job_id=crawl_job.id,
                source_site="offertoday",
                source_job_id="missing",
            ),
            _running_listing(
                row_id=304,
                detail_crawl_job_id=crawl_job.id,
                source_site="jobsdb",
                source_job_id="same-id",
            ),
        ]
        rows[0].published_job_id = incomplete_job.id
        rows[2].published_job_id = complete_shared_job.id
        db.add_all(
            [company, crawl_job, complete_shared_job, incomplete_job, *rows]
        )
        db.commit()

        _recover_crawls(db)
        for row in rows:
            db.refresh(row)

        assert [row.detail_status for row in rows] == ["failed", "failed", "failed"]
        assert all(
            row.detail_error_message == CRAWL_JOB_RESTART_MESSAGE for row in rows
        )
        assert all(row.detail_completed_at is not None for row in rows)
        assert all(row.published_job_id is None for row in rows)
        assert db.query(CrawlJobListing).filter(
            CrawlJobListing.last_detail_crawl_job_id == crawl_job.id,
            CrawlJobListing.detail_status == "running",
        ).count() == 0
    finally:
        db.close()


def test_multiple_recovered_crawl_jobs_emit_deterministic_per_job_records():
    db = _build_session()
    try:
        company = _company()
        crawl_a = _crawl_job(row_id=103)
        crawl_b = _crawl_job(row_id=104)
        complete_a = _published_job(
            "a-complete",
            company_id=company.id,
            row_id=204,
        )
        complete_b = _published_job(
            "b-complete",
            company_id=company.id,
            row_id=205,
        )
        rows = [
            _running_listing(
                row_id=307,
                detail_crawl_job_id=crawl_b.id,
                source_site="offertoday",
                source_job_id="b-missing",
            ),
            _running_listing(
                row_id=306,
                detail_crawl_job_id=crawl_a.id,
                source_site="offertoday",
                source_job_id="a-missing",
            ),
            _running_listing(
                row_id=305,
                detail_crawl_job_id=crawl_a.id,
                source_site="offertoday",
                source_job_id="a-complete",
            ),
            _running_listing(
                row_id=308,
                detail_crawl_job_id=crawl_b.id,
                source_site="offertoday",
                source_job_id="b-complete",
            ),
        ]
        db.add_all([company, crawl_a, crawl_b, complete_a, complete_b, *rows])
        db.commit()

        summary = _recover_crawls(db)

        events = (
            db.query(CrawlJobEvent)
            .filter(CrawlJobEvent.event_type == "crawl.detail_recovered")
            .order_by(CrawlJobEvent.crawl_job_id.asc())
            .all()
        )
        assert summary["crawl_jobs_recovered"] == 2
        assert [event.crawl_job_id for event in events] == [crawl_a.id, crawl_b.id]
        assert [
            [record["source_job_id"] for record in event.payload["records"]]
            for event in events
        ] == [
            ["a-complete", "a-missing"],
            ["b-complete", "b-missing"],
        ]
        assert all(
            record["counts_as_fetch_success"] is False
            for event in events
            for record in event.payload["records"]
        )
        assert db.query(CrawlJobListing).filter(
            CrawlJobListing.last_detail_crawl_job_id.in_([crawl_a.id, crawl_b.id]),
            CrawlJobListing.detail_status == "running",
        ).count() == 0
    finally:
        db.close()


def test_recovery_event_failure_rolls_back_crawl_and_detail_transitions(monkeypatch):
    db = _build_session()
    try:
        crawl_job = _crawl_job(row_id=105, source_site="jobsdb")
        listing = _running_listing(
            row_id=309,
            detail_crawl_job_id=crawl_job.id,
            source_site="jobsdb",
            source_job_id="jobsdb-1",
        )
        db.add_all([crawl_job, listing])
        db.commit()

        def fail_event(*args, **kwargs):
            raise RuntimeError("event write failed")

        monkeypatch.setattr(CrawlJobRepository, "append_event", fail_event)

        summary = _recover_crawls(db)
        db.expire_all()
        restored_crawl = db.get(CrawlJob, crawl_job.id)
        restored_listing = db.get(CrawlJobListing, listing.id)

        assert summary["crawl_jobs_recovered"] == 0
        assert restored_crawl.status == "running"
        assert restored_crawl.completed_at is None
        assert restored_listing.detail_status == "running"
        assert restored_listing.detail_completed_at is None
        assert db.query(CrawlJobEvent).count() == 0
    finally:
        db.close()


def test_recovery_options_preserve_other_startup_subsystem_behavior(monkeypatch):
    class _RecordingDb:
        def __init__(self) -> None:
            self.commits = 0
            self.rollbacks = 0

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

    db = _RecordingDb()
    service = StartupRecoveryService(db)
    calls: list[str] = []
    monkeypatch.setattr(service, "_recover_ai_runs", lambda: calls.append("ai") or 1)
    monkeypatch.setattr(
        service,
        "_recover_company_runs",
        lambda: calls.append("company") or 2,
    )
    monkeypatch.setattr(
        service,
        "_recover_crawl_jobs",
        lambda: calls.append("crawl") or 3,
    )
    monkeypatch.setattr(
        service,
        "_recover_schedule_executions",
        lambda: calls.append("schedule") or 4,
    )

    summary = service.recover_interrupted_operations(
        recover_ai_runs=False,
        recover_company_runs=True,
        recover_crawl_jobs=False,
        recover_schedule_executions=True,
    )

    assert calls == ["company", "schedule"]
    assert summary == {
        "ai_runs_recovered": 0,
        "company_runs_recovered": 2,
        "crawl_jobs_recovered": 0,
        "schedule_executions_recovered": 4,
    }
    assert db.commits == 2
    assert db.rollbacks == 0
