from __future__ import annotations

import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import CrawlJob, CrawlJobListing
from app.repositories.crawl_job_listing_repository import CrawlJobListingRepository


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            CrawlJob.__table__,
            CrawlJobListing.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def _create_crawl_job(db, *, source_site: str = "jobsdb") -> CrawlJob:
    crawl_job = CrawlJob(
        id=uuid.uuid4(),
        source_site=source_site,
        trigger_type="manual",
        status="queued",
        request_payload={"source_site": source_site},
        requested_by="pytest",
    )
    db.add(crawl_job)
    db.commit()
    db.refresh(crawl_job)
    return crawl_job


def test_upsert_listing_creates_and_updates_a_single_row_per_crawl_job():
    db = _build_sqlite_session()
    try:
        crawl_job = _create_crawl_job(db)
        repository = CrawlJobListingRepository()

        listing, action = repository.upsert_listing(
            db,
            crawl_job_id=crawl_job.id,
            source_site="jobsdb",
            source_job_id="123456",
            source_url="https://hk.jobsdb.com/job/123456",
            source_classification_id="6281",
            source_classification_name="ICT",
            listing_page=3,
            listing_rank=1,
            listing_payload={"title": "Senior Data Analyst"},
        )

        assert action == "created"
        assert listing.detail_status == "pending"
        assert listing.detail_attempts == 0

        updated, action = repository.upsert_listing(
            db,
            crawl_job_id=crawl_job.id,
            source_site="jobsdb",
            source_job_id="123456",
            source_url="https://hk.jobsdb.com/job/123456",
            source_classification_id="6281",
            source_classification_name="Information Technology",
            listing_page=2,
            listing_rank=4,
            listing_payload={"title": "Senior Data Analyst", "location": "Hong Kong"},
        )

        assert action == "updated"
        assert updated.id == listing.id
        assert updated.source_classification_name == "Information Technology"
        assert updated.listing_page == 2
        assert updated.listing_rank == 4
        assert updated.listing_payload["location"] == "Hong Kong"
        assert db.query(CrawlJobListing).count() == 1
    finally:
        db.close()


def test_list_detail_candidates_filters_by_status_category_and_source_listing_crawl_job():
    db = _build_sqlite_session()
    try:
        listing_crawl_job = _create_crawl_job(db, source_site="jobsdb")
        other_listing_crawl_job = _create_crawl_job(db, source_site="jobsdb")
        detail_crawl_job = _create_crawl_job(db, source_site="jobsdb")
        repository = CrawlJobListingRepository()

        first_listing, _ = repository.upsert_listing(
            db,
            crawl_job_id=listing_crawl_job.id,
            source_site="jobsdb",
            source_job_id="123456",
            source_url="https://hk.jobsdb.com/job/123456",
            source_classification_id="6281",
            source_classification_name="ICT",
            listing_page=3,
            listing_rank=1,
            listing_payload={"title": "First"},
        )
        second_listing, _ = repository.upsert_listing(
            db,
            crawl_job_id=listing_crawl_job.id,
            source_site="jobsdb",
            source_job_id="234567",
            source_url="https://hk.jobsdb.com/job/234567",
            source_classification_id="6282",
            source_classification_name="Data Science",
            listing_page=3,
            listing_rank=2,
            listing_payload={"title": "Second"},
        )
        third_listing, _ = repository.upsert_listing(
            db,
            crawl_job_id=other_listing_crawl_job.id,
            source_site="jobsdb",
            source_job_id="345678",
            source_url="https://hk.jobsdb.com/job/345678",
            source_classification_id="6281",
            source_classification_name="ICT",
            listing_page=2,
            listing_rank=1,
            listing_payload={"title": "Third"},
        )

        repository.mark_detail_running(
            db,
            listing_id=second_listing.id,
            detail_crawl_job_id=detail_crawl_job.id,
        )
        repository.mark_detail_completed(
            db,
            listing_id=second_listing.id,
            detail_crawl_job_id=detail_crawl_job.id,
            published_job_id=uuid.uuid4(),
        )
        repository.mark_detail_failed(
            db,
            listing_id=third_listing.id,
            detail_crawl_job_id=detail_crawl_job.id,
            error_message="timeout",
        )

        pending = repository.list_detail_candidates(
            db,
            source_site="jobsdb",
            source_listing_crawl_job_id=listing_crawl_job.id,
            category_ids=["6281", "6282"],
            statuses=("pending",),
            limit=10,
        )
        failed = repository.list_detail_candidates(
            db,
            source_site="jobsdb",
            category_ids=["6281"],
            statuses=("failed",),
            limit=10,
        )

        assert [row.id for row in pending] == [first_listing.id]
        assert [row.id for row in failed] == [third_listing.id]
    finally:
        db.close()


def test_mark_detail_running_completed_and_failed_updates_listing_state():
    db = _build_sqlite_session()
    try:
        listing_crawl_job = _create_crawl_job(db, source_site="ctgoodjobs")
        detail_crawl_job = _create_crawl_job(db, source_site="ctgoodjobs")
        repository = CrawlJobListingRepository()

        listing, _ = repository.upsert_listing(
            db,
            crawl_job_id=listing_crawl_job.id,
            source_site="ctgoodjobs",
            source_job_id="10090657",
            source_url="https://jobs.ctgoodjobs.hk/job/10090657",
            source_classification_id="ctgoodjobs:021",
            source_classification_name="Information Technology",
            listing_page=4,
            listing_rank=1,
            listing_payload={"job_id": "10090657"},
        )

        running = repository.mark_detail_running(
            db,
            listing_id=listing.id,
            detail_crawl_job_id=detail_crawl_job.id,
        )
        assert running.detail_status == "running"
        assert running.detail_attempts == 1
        assert running.detail_started_at is not None
        assert running.last_detail_crawl_job_id == detail_crawl_job.id

        completed = repository.mark_detail_completed(
            db,
            listing_id=listing.id,
            detail_crawl_job_id=detail_crawl_job.id,
            published_job_id=uuid.uuid4(),
        )
        assert completed.detail_status == "completed"
        assert completed.published_job_id is not None
        assert completed.detail_completed_at is not None
        assert completed.detail_error_message is None

        failed = repository.mark_detail_failed(
            db,
            listing_id=listing.id,
            detail_crawl_job_id=detail_crawl_job.id,
            error_message="retry exhausted",
        )
        assert failed.detail_status == "failed"
        assert failed.detail_error_message == "retry exhausted"
        assert failed.detail_completed_at is not None
    finally:
        db.close()


def test_list_detail_candidates_prioritizes_manual_action_required_before_pending():
    db = _build_sqlite_session()
    try:
        listing_crawl_job = _create_crawl_job(db, source_site="ctgoodjobs")
        detail_crawl_job = _create_crawl_job(db, source_site="ctgoodjobs")
        repository = CrawlJobListingRepository()

        pending_listing, _ = repository.upsert_listing(
            db,
            crawl_job_id=listing_crawl_job.id,
            source_site="ctgoodjobs",
            source_job_id="10090657",
            source_url="https://jobs.ctgoodjobs.hk/job/10090657",
            source_classification_id="ctgoodjobs:021",
            source_classification_name="Information Technology",
            listing_page=1,
            listing_rank=1,
            listing_payload={"job_id": "10090657"},
        )
        manual_action_listing, _ = repository.upsert_listing(
            db,
            crawl_job_id=listing_crawl_job.id,
            source_site="ctgoodjobs",
            source_job_id="10090658",
            source_url="https://jobs.ctgoodjobs.hk/job/10090658",
            source_classification_id="ctgoodjobs:021",
            source_classification_name="Information Technology",
            listing_page=1,
            listing_rank=2,
            listing_payload={"job_id": "10090658"},
        )

        repository.mark_detail_manual_action_required(
            db,
            listing_id=manual_action_listing.id,
            detail_crawl_job_id=detail_crawl_job.id,
            error_message="captcha encountered",
        )

        candidates = repository.list_detail_candidates(
            db,
            source_site="ctgoodjobs",
            source_listing_crawl_job_id=listing_crawl_job.id,
            statuses=("manual_action_required", "pending"),
            limit=10,
        )

        assert [row.id for row in candidates] == [manual_action_listing.id, pending_listing.id]
    finally:
        db.close()
