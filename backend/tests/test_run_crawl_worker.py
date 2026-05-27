from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.crawl_job import CrawlJob
from app.models.crawl_job_listing import CrawlJobListing
from app.models.schedule import ScrapeSchedule
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.workers.run_crawl_worker import CrawlWorkerService


class FakeBus:
    def ensure_group(self, *_args, **_kwargs) -> None:
        return None


class FakeJobRepository:
    def __init__(self, existing_by_source_job_id: dict[str, object] | None = None) -> None:
        self.existing_by_source_job_id = dict(existing_by_source_job_id or {})

    def list_existing_jobs_by_source_ids(self, db, *, source_site: str, source_job_ids: list[str]):
        return {
            source_job_id: self.existing_by_source_job_id[source_job_id]
            for source_job_id in source_job_ids
            if source_job_id in self.existing_by_source_job_id
        }


def _build_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            CrawlJob.__table__,
            CrawlJobListing.__table__,
        ],
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _create_crawl_job(db, *, source_site: str = "jobsdb", request_payload: dict | None = None) -> CrawlJob:
    crawl_job = CrawlJob(
        source_site=source_site,
        trigger_type="manual",
        status="queued",
        request_payload=dict(request_payload or {"crawl_phase": "detail", "source_site": source_site}),
        queued_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
    )
    db.add(crawl_job)
    db.commit()
    db.refresh(crawl_job)
    return crawl_job


def _create_listing(
    db,
    *,
    crawl_job_id,
    source_job_id: str,
    detail_status: str,
    category_id: str = "1200",
    listing_rank: int,
) -> CrawlJobListing:
    listing = CrawlJobListing(
        crawl_job_id=crawl_job_id,
        source_site="jobsdb",
        source_job_id=source_job_id,
        source_url=f"https://example.test/jobs/{source_job_id}",
        source_classification_id=category_id,
        source_classification_name="Engineering",
        listing_page=1,
        listing_rank=listing_rank,
        listing_payload={"source_job_id": source_job_id},
        detail_status=detail_status,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def test_build_manual_request_payload_defaults_detail_runs_to_retry_pool():
    service = CrawlJobDispatchService()

    payload = service.build_manual_request_payload(
        source_site="jobsdb",
        crawl_phase="detail",
        category_ids=[1200],
        max_pages=3,
        detail_limit=250,
    )

    assert payload["detail_statuses"] == ["pending", "failed", "manual_action_required"]
    assert payload["detail_limit"] == 250
    assert payload["source_listing_crawl_job_id"] is None


def test_load_detail_targets_uses_retry_pool_defaults_and_tracks_skip_existing_metrics():
    session_factory = _build_session_factory()
    db = session_factory()
    source_batch_a = _create_crawl_job(db, request_payload={"crawl_phase": "listing", "source_site": "jobsdb"})
    source_batch_b = _create_crawl_job(db, request_payload={"crawl_phase": "listing", "source_site": "jobsdb"})
    detail_crawl_job = _create_crawl_job(
        db,
        request_payload={"crawl_phase": "detail", "source_site": "jobsdb", "category_ids": [1200]},
    )

    manual_row = _create_listing(
        db,
        crawl_job_id=source_batch_a.id,
        source_job_id="manual-row",
        detail_status="manual_action_required",
        listing_rank=4,
    )
    failed_row = _create_listing(
        db,
        crawl_job_id=source_batch_b.id,
        source_job_id="failed-row",
        detail_status="failed",
        listing_rank=2,
    )
    pending_row = _create_listing(
        db,
        crawl_job_id=source_batch_a.id,
        source_job_id="pending-row",
        detail_status="pending",
        listing_rank=3,
    )
    skipped_row = _create_listing(
        db,
        crawl_job_id=source_batch_b.id,
        source_job_id="skip-existing-row",
        detail_status="pending",
        listing_rank=5,
    )
    _create_listing(
        db,
        crawl_job_id=source_batch_b.id,
        source_job_id="completed-row",
        detail_status="completed",
        listing_rank=1,
    )
    manual_row_id = manual_row.id
    failed_row_id = failed_row.id
    pending_row_id = pending_row.id
    detail_crawl_job_id = detail_crawl_job.id
    skipped_row_id = skipped_row.id
    db.close()

    worker = CrawlWorkerService(
        bus=FakeBus(),
        runner_registry={},
        job_repository=FakeJobRepository(
            existing_by_source_job_id={
                "skip-existing-row": SimpleNamespace(id=uuid4()),
            }
        ),
        session_factory=session_factory,
    )

    load_result = worker._load_detail_targets(
        source_site="jobsdb",
        request_payload={
            "crawl_phase": "detail",
            "category_ids": [1200],
            "detail_limit": 10,
            "skip_existing": True,
        },
        detail_crawl_job_id=str(detail_crawl_job_id),
    )

    assert [target["listing_id"] for target in load_result.targets] == [
        str(manual_row_id),
        str(failed_row_id),
        str(pending_row_id),
    ]
    assert load_result.selected_rows == 4
    assert load_result.skipped_existing_rows == 1
    assert load_result.target_rows == 3

    verification_db = session_factory()
    crawl_job_repository = CrawlJobRepository()
    refreshed_detail_job = crawl_job_repository.get_crawl_job_by_id(verification_db, detail_crawl_job_id)
    refreshed_skipped_row = (
        verification_db.query(CrawlJobListing)
        .filter(CrawlJobListing.id == skipped_row_id)
        .one()
    )

    assert refreshed_detail_job.metrics["detail_selected_rows"] == 4
    assert refreshed_detail_job.metrics["detail_skipped_existing_rows"] == 1
    assert refreshed_detail_job.metrics["detail_target_rows"] == 3
    assert refreshed_skipped_row.detail_status == "completed"
    assert refreshed_skipped_row.detail_payload["skip_existing"] is True
    verification_db.close()


def test_load_detail_targets_keeps_filling_until_detail_limit_after_skip_existing():
    session_factory = _build_session_factory()
    db = session_factory()
    source_batch = _create_crawl_job(db, request_payload={"crawl_phase": "listing", "source_site": "jobsdb"})
    detail_crawl_job = _create_crawl_job(
        db,
        request_payload={"crawl_phase": "detail", "source_site": "jobsdb", "category_ids": [1200]},
    )

    skipped_row_a = _create_listing(
        db,
        crawl_job_id=source_batch.id,
        source_job_id="skip-existing-row-a",
        detail_status="pending",
        listing_rank=1,
    )
    skipped_row_b = _create_listing(
        db,
        crawl_job_id=source_batch.id,
        source_job_id="skip-existing-row-b",
        detail_status="pending",
        listing_rank=2,
    )
    target_row_a = _create_listing(
        db,
        crawl_job_id=source_batch.id,
        source_job_id="target-row-a",
        detail_status="pending",
        listing_rank=3,
    )
    target_row_b = _create_listing(
        db,
        crawl_job_id=source_batch.id,
        source_job_id="target-row-b",
        detail_status="pending",
        listing_rank=4,
    )
    untouched_row = _create_listing(
        db,
        crawl_job_id=source_batch.id,
        source_job_id="untouched-row",
        detail_status="pending",
        listing_rank=5,
    )
    skipped_row_a_id = skipped_row_a.id
    skipped_row_b_id = skipped_row_b.id
    target_row_a_id = target_row_a.id
    target_row_b_id = target_row_b.id
    untouched_row_id = untouched_row.id
    detail_crawl_job_id = detail_crawl_job.id
    db.close()

    worker = CrawlWorkerService(
        bus=FakeBus(),
        runner_registry={},
        job_repository=FakeJobRepository(
            existing_by_source_job_id={
                "skip-existing-row-a": SimpleNamespace(id=uuid4()),
                "skip-existing-row-b": SimpleNamespace(id=uuid4()),
            }
        ),
        session_factory=session_factory,
    )

    load_result = worker._load_detail_targets(
        source_site="jobsdb",
        request_payload={
            "crawl_phase": "detail",
            "category_ids": [1200],
            "detail_limit": 2,
            "skip_existing": True,
        },
        detail_crawl_job_id=str(detail_crawl_job_id),
    )

    assert [target["listing_id"] for target in load_result.targets] == [
        str(target_row_a_id),
        str(target_row_b_id),
    ]
    assert load_result.selected_rows == 4
    assert load_result.skipped_existing_rows == 2
    assert load_result.target_rows == 2

    verification_db = session_factory()
    crawl_job_repository = CrawlJobRepository()
    refreshed_detail_job = crawl_job_repository.get_crawl_job_by_id(verification_db, detail_crawl_job_id)
    refreshed_skipped_rows = (
        verification_db.query(CrawlJobListing)
        .filter(CrawlJobListing.id.in_([skipped_row_a_id, skipped_row_b_id]))
        .order_by(CrawlJobListing.listing_rank.asc())
        .all()
    )
    refreshed_untouched_row = (
        verification_db.query(CrawlJobListing)
        .filter(CrawlJobListing.id == untouched_row_id)
        .one()
    )

    assert refreshed_detail_job.metrics["detail_selected_rows"] == 4
    assert refreshed_detail_job.metrics["detail_skipped_existing_rows"] == 2
    assert refreshed_detail_job.metrics["detail_target_rows"] == 2
    assert [row.detail_status for row in refreshed_skipped_rows] == ["completed", "completed"]
    assert refreshed_untouched_row.detail_status == "pending"
    verification_db.close()
