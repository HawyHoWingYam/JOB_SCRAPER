from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.crawl_job import CrawlJob
from app.models.crawl_job_listing import CrawlJobListing
from app.models.schedule import ScrapeSchedule
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository


def _build_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            CrawlJob.__table__,
            CrawlJobListing.__table__,
        ],
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def _create_crawl_job(db, *, source_site: str = "jobsdb") -> CrawlJob:
    crawl_job = CrawlJob(
        source_site=source_site,
        trigger_type="manual",
        status="completed",
        request_payload={"crawl_phase": "listing", "source_site": source_site},
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
    created_at: datetime,
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
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)
    return listing


def test_list_detail_candidates_uses_global_retry_pool_and_orders_manual_rows_first():
    db = _build_session()
    repository = CrawlJobListingRepository()
    first_batch = _create_crawl_job(db)
    second_batch = _create_crawl_job(db)
    base_time = datetime(2026, 5, 27, 9, 0, tzinfo=UTC)

    manual_row = _create_listing(
        db,
        crawl_job_id=first_batch.id,
        source_job_id="manual-row",
        detail_status="manual_action_required",
        listing_rank=5,
        created_at=base_time,
    )
    failed_row = _create_listing(
        db,
        crawl_job_id=second_batch.id,
        source_job_id="failed-row",
        detail_status="failed",
        listing_rank=2,
        created_at=base_time + timedelta(seconds=1),
    )
    pending_row = _create_listing(
        db,
        crawl_job_id=first_batch.id,
        source_job_id="pending-row",
        detail_status="pending",
        listing_rank=3,
        created_at=base_time + timedelta(seconds=2),
    )
    _create_listing(
        db,
        crawl_job_id=second_batch.id,
        source_job_id="completed-row",
        detail_status="completed",
        listing_rank=1,
        created_at=base_time + timedelta(seconds=3),
    )
    _create_listing(
        db,
        crawl_job_id=second_batch.id,
        source_job_id="other-category",
        detail_status="pending",
        category_id="6281",
        listing_rank=1,
        created_at=base_time + timedelta(seconds=4),
    )

    rows = repository.list_detail_candidates(
        db,
        source_site="jobsdb",
        category_ids=["1200"],
        limit=10,
    )

    assert [row.id for row in rows] == [manual_row.id, failed_row.id, pending_row.id]


def test_list_detail_candidates_allows_optional_listing_batch_narrowing():
    db = _build_session()
    repository = CrawlJobListingRepository()
    first_batch = _create_crawl_job(db)
    second_batch = _create_crawl_job(db)
    base_time = datetime(2026, 5, 27, 9, 0, tzinfo=UTC)

    first_pending = _create_listing(
        db,
        crawl_job_id=first_batch.id,
        source_job_id="first-batch-pending",
        detail_status="pending",
        listing_rank=2,
        created_at=base_time,
    )
    first_failed = _create_listing(
        db,
        crawl_job_id=first_batch.id,
        source_job_id="first-batch-failed",
        detail_status="failed",
        listing_rank=3,
        created_at=base_time + timedelta(seconds=1),
    )
    _create_listing(
        db,
        crawl_job_id=second_batch.id,
        source_job_id="second-batch-manual",
        detail_status="manual_action_required",
        listing_rank=1,
        created_at=base_time + timedelta(seconds=2),
    )

    rows = repository.list_detail_candidates(
        db,
        source_site="jobsdb",
        source_listing_crawl_job_id=first_batch.id,
        category_ids=["1200"],
        limit=10,
    )

    assert [row.id for row in rows] == [first_pending.id, first_failed.id]
