from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.company import Company
from app.models.crawl_dispatch_plan import (
    CRAWL_DISPATCH_PLAN_TABLES,
    CrawlDispatchPlan,
    CrawlDispatchPlanTarget,
    CrawlDispatchPlanTargetRow,
)
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_execution import CrawlJobExecution
from app.models.crawl_job_listing import CrawlJobListing
from app.models.job import Job
from app.models.schedule import ScheduleExecution, ScrapeSchedule
from app.services.crawl_listing_deduplication_service import (
    APPROVED_CRAWL_JOB_SOURCES,
    APPROVED_JOBSDB_DISPATCH_PLANS,
    CrawlListingDeduplicationService,
)


@compiles(PostgreSQLUUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@pytest.fixture
def cleanup_db():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    tables = (
        Company.__table__,
        Job.__table__,
        ScrapeSchedule.__table__,
        *CRAWL_DISPATCH_PLAN_TABLES,
        CrawlJob.__table__,
        CrawlJobEvent.__table__,
        CrawlJobExecution.__table__,
        CrawlJobListing.__table__,
        ScheduleExecution.__table__,
    )
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            Base.metadata.drop_all(connection, tables=reversed(tables))
        engine.dispose()


def _crawl_job(crawl_job_id: UUID, source_site: str) -> CrawlJob:
    return CrawlJob(
        id=crawl_job_id,
        source_site=source_site,
        trigger_type="manual",
        status="completed",
        request_payload={"crawl_phase": "listing"},
        metrics={"pages_processed": 200, "jobs_saved": 87},
    )


def _listing(crawl_job_id: UUID, source_site: str, source_job_id: str, status: str):
    return CrawlJobListing(
        crawl_job_id=crawl_job_id,
        source_site=source_site,
        source_job_id=source_job_id,
        source_url=f"https://example.test/{source_site}/{source_job_id}",
        listing_payload={},
        detail_status=status,
    )


def _published_job(company_id, source_site: str, source_job_id: str) -> Job:
    return Job(
        job_id=f"{source_site}:{source_job_id}",
        source_site=source_site,
        source_job_id=source_job_id,
        company_id=company_id,
        title=source_job_id,
        is_deleted=False,
    )


def _dispatch_plan(
    *,
    plan_id: UUID,
    state: str,
    crawl_job_id: UUID | None,
    listing_rows: list[CrawlJobListing],
) -> CrawlDispatchPlan:
    now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
    return CrawlDispatchPlan(
        id=plan_id,
        state=state,
        source_site="jobsdb",
        crawl_phase="detail",
        trigger_kind="one_off",
        authored_scope={},
        resolved_scope={},
        listing_settings=None,
        detail_settings={},
        readiness={},
        detail_target_count=len(listing_rows),
        plan_fingerprint=str(plan_id).replace("-", "") * 2,
        confirmation_required=False,
        confirmation_token_hash=None,
        prepared_by="cleanup-test",
        prepared_at=now,
        expires_at=now + timedelta(hours=1),
        consumed_at=now + timedelta(minutes=1) if state == "consumed" else None,
        crawl_job_id=crawl_job_id,
        targets=[
            CrawlDispatchPlanTarget(
                source_site="jobsdb",
                source_job_id=row.source_job_id,
                selection_order=index,
                eligibility_fingerprint="a" * 64,
                eligibility_status=row.detail_status,
                status_metadata={},
                rows=[
                    CrawlDispatchPlanTargetRow(
                        crawl_job_listing_id=row.id,
                        row_order=0,
                        eligibility_fingerprint="b" * 64,
                        eligibility_status=row.detail_status,
                        status_metadata={},
                    )
                ],
            )
            for index, row in enumerate(listing_rows)
        ],
    )


def _seed_cleanup_scope(db):
    ct_id = UUID("720df33d-bcca-4ec0-b6e0-0da1f9c01a4f")
    jobsdb_id = UUID("06e326b2-c4bf-440c-b196-b1a04fc8d6a5")
    company = Company(
        company_id="cleanup-company",
        source_site="jobsdb",
        source_company_id="cleanup-company",
        name="Cleanup Company",
    )
    db.add(company)
    db.flush()
    detail_crawl_job_id = UUID("bd343e54-a79d-4547-9fd5-57a7f49f5510")
    detail_crawl_job = _crawl_job(detail_crawl_job_id, "jobsdb")
    detail_crawl_job.status = "cancelled"
    detail_crawl_job.request_payload = {
        "source_site": "jobsdb",
        "crawl_phase": "detail",
        "crawl_mode": "headless",
        "detail_scope": "crawl_scope",
        "detail_limit": 3,
    }
    db.add_all(
        [
            _crawl_job(ct_id, "ctgoodjobs"),
            _crawl_job(jobsdb_id, "jobsdb"),
            detail_crawl_job,
            _published_job(company.id, "ctgoodjobs", "ct-existing"),
            _published_job(company.id, "jobsdb", "jobs-existing-pending"),
            _published_job(company.id, "jobsdb", "jobs-existing-completed"),
        ]
    )
    db.add_all(
        [
            _listing(ct_id, "ctgoodjobs", "ct-existing", "pending"),
            _listing(ct_id, "ctgoodjobs", "ct-missing", "pending"),
            _listing(jobsdb_id, "jobsdb", "jobs-existing-pending", "pending"),
            _listing(
                jobsdb_id,
                "jobsdb",
                "jobs-existing-completed",
                "completed",
            ),
            _listing(jobsdb_id, "jobsdb", "jobs-missing", "failed"),
        ]
    )
    db.flush()
    jobsdb_listing_rows = (
        db.query(CrawlJobListing)
        .filter(CrawlJobListing.crawl_job_id == jobsdb_id)
        .order_by(CrawlJobListing.id.asc())
        .all()
    )
    consumed_plan_id = UUID("0c4418c9-2327-4c75-8268-f71f62369cd2")
    prepared_plan_id = UUID("ba27b116-21f1-4440-b163-1d899ee3fe43")
    db.add_all(
        [
            _dispatch_plan(
                plan_id=consumed_plan_id,
                state="consumed",
                crawl_job_id=detail_crawl_job_id,
                listing_rows=jobsdb_listing_rows,
            ),
            _dispatch_plan(
                plan_id=prepared_plan_id,
                state="prepared",
                crawl_job_id=None,
                listing_rows=jobsdb_listing_rows,
            ),
        ]
    )
    db.flush()
    db.execute(
        update(CrawlJob.__table__)
        .where(CrawlJob.id == detail_crawl_job_id)
        .values(
            dispatch_plan_id=consumed_plan_id,
            dispatch_plan_fingerprint=str(consumed_plan_id).replace("-", "") * 2,
        )
    )
    db.add_all(
        [
            CrawlJobEvent(
                crawl_job_id=ct_id,
                sequence_no=1,
                event_type="crawl.completed",
                payload={},
                emitted_by="test",
            ),
            CrawlJobEvent(
                crawl_job_id=jobsdb_id,
                sequence_no=1,
                event_type="crawl.completed",
                payload={},
                emitted_by="test",
            ),
            CrawlJobExecution(
                crawl_job_id=ct_id,
                generation=uuid4(),
                launcher_instance_id="test-launcher",
                status="exited",
                command=["python", "ctgoodjobs"],
                exit_code=0,
            ),
            CrawlJobExecution(
                crawl_job_id=jobsdb_id,
                generation=uuid4(),
                launcher_instance_id="test-launcher",
                status="exited",
                command=["python", "jobsdb"],
                exit_code=0,
            ),
        ]
    )
    db.commit()
    return ct_id, jobsdb_id, detail_crawl_job_id


def test_cleanup_is_dry_run_first_fenced_atomic_and_idempotent(cleanup_db) -> None:
    ct_id, jobsdb_id, detail_crawl_job_id = _seed_cleanup_scope(cleanup_db)
    service = CrawlListingDeduplicationService(cleanup_db)

    previews = service.run()
    preview_by_id = {preview.crawl_job_id: preview for preview in previews}
    assert preview_by_id[ct_id].matched_rows == 1
    assert preview_by_id[ct_id].retained_rows == 1
    assert preview_by_id[jobsdb_id].matched_rows == 2
    assert preview_by_id[jobsdb_id].retained_rows == 1
    assert set(preview_by_id[jobsdb_id].dispatch_plan_ids) == set(
        APPROVED_JOBSDB_DISPATCH_PLANS
    )
    assert preview_by_id[jobsdb_id].dispatch_plan_target_rows == 6
    assert preview_by_id[jobsdb_id].detached_crawl_job_ids == (detail_crawl_job_id,)
    assert cleanup_db.query(CrawlJobListing).count() == 5

    with pytest.raises(RuntimeError, match="matched-row fence changed"):
        service.run(
            execute=True,
            expected_matched_rows={ct_id: 999, jobsdb_id: 2},
        )
    cleanup_db.rollback()
    assert cleanup_db.query(CrawlJobListing).count() == 5

    before_jobs = cleanup_db.query(Job).count()
    before_events = cleanup_db.query(CrawlJobEvent).count()
    before_executions = cleanup_db.query(CrawlJobExecution).count()
    before_crawl_jobs = cleanup_db.query(CrawlJob).count()
    applied = service.run(
        execute=True,
        expected_matched_rows={ct_id: 1, jobsdb_id: 2},
    )
    cleanup_db.commit()

    assert {preview.matched_rows for preview in applied} == {1, 2}
    assert cleanup_db.query(Job).count() == before_jobs
    assert cleanup_db.query(CrawlJobEvent).count() == before_events
    assert cleanup_db.query(CrawlJobExecution).count() == before_executions
    assert cleanup_db.query(CrawlJob).count() == before_crawl_jobs
    assert cleanup_db.query(CrawlDispatchPlan).count() == 0
    assert cleanup_db.query(CrawlDispatchPlanTarget).count() == 0
    assert cleanup_db.query(CrawlDispatchPlanTargetRow).count() == 0
    detached_job = (
        cleanup_db.query(
            CrawlJob.status,
            CrawlJob.dispatch_plan_id,
            CrawlJob.dispatch_plan_fingerprint,
            CrawlJob.request_payload,
        )
        .filter(CrawlJob.id == detail_crawl_job_id)
        .one()
    )
    assert detached_job.status == "cancelled"
    assert detached_job.dispatch_plan_id is None
    assert detached_job.dispatch_plan_fingerprint is None
    assert detached_job.request_payload["removed_dispatch_plan"] == {
        "reason": "historical_listing_deduplication",
        "plan_id": "0c4418c9-2327-4c75-8268-f71f62369cd2",
        "plan_fingerprint": str(
            detached_job.request_payload["dispatch_plan_fingerprint"]
        ),
    }
    assert {
        row.source_job_id
        for row in cleanup_db.query(CrawlJobListing)
        .filter(CrawlJobListing.crawl_job_id == ct_id)
        .all()
    } == {"ct-missing"}
    assert {
        row.source_job_id
        for row in cleanup_db.query(CrawlJobListing)
        .filter(CrawlJobListing.crawl_job_id == jobsdb_id)
        .all()
    } == {"jobs-missing"}

    ct_metrics = (
        cleanup_db.query(CrawlJob.metrics).filter(CrawlJob.id == ct_id).scalar()
    )
    jobsdb_metrics = (
        cleanup_db.query(CrawlJob.metrics).filter(CrawlJob.id == jobsdb_id).scalar()
    )
    assert "pages_processed" not in ct_metrics
    assert "pages_processed" not in jobsdb_metrics
    assert ct_metrics["raw_job_ids_collected"] == 1
    assert ct_metrics["detail_pending"] == 1
    assert jobsdb_metrics["raw_job_ids_collected"] == 1
    assert jobsdb_metrics["detail_failed"] == 1
    assert jobsdb_metrics["detail_completed"] == 0
    assert ct_metrics["jobs_saved"] == jobsdb_metrics["jobs_saved"] == 0

    second = service.run(
        execute=True,
        expected_matched_rows={
            crawl_job_id: 0 for crawl_job_id in APPROVED_CRAWL_JOB_SOURCES
        },
    )
    cleanup_db.commit()
    assert all(preview.matched_rows == 0 for preview in second)
    assert cleanup_db.query(CrawlJobListing).count() == 2


def test_cleanup_rejects_unexpected_schedule_execution_reference(cleanup_db) -> None:
    _seed_cleanup_scope(cleanup_db)
    prepared_plan_id = UUID("ba27b116-21f1-4440-b163-1d899ee3fe43")
    prepared_plan = (
        cleanup_db.query(CrawlDispatchPlan).filter_by(id=prepared_plan_id).one()
    )
    cleanup_db.add(
        ScheduleExecution(
            status="completed",
            dispatch_plan_id=prepared_plan_id,
            dispatch_plan_fingerprint=prepared_plan.plan_fingerprint,
        )
    )
    cleanup_db.commit()

    with pytest.raises(RuntimeError, match="Schedule Execution reference"):
        CrawlListingDeduplicationService(cleanup_db).run()
