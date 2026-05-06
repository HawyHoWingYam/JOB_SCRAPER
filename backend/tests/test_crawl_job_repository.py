import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.models import CrawlJob, CrawlJobEvent, EventOutbox, ScheduleExecution, ScrapeSchedule
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.repositories.event_outbox_repository import EventOutboxRepository


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
            ScrapeSchedule.__table__,
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
            EventOutbox.__table__,
            ScheduleExecution.__table__,
        ],
    )
    Session = sessionmaker(bind=engine)
    return Session()


def test_schedule_execution_tracks_crawl_job_link():
    assert hasattr(ScheduleExecution, "crawl_job_id")


def test_crawl_job_repository_creates_job_and_sequences_events():
    db = _build_sqlite_session()
    try:
        repository = CrawlJobRepository()

        crawl_job = repository.create_crawl_job(
            db,
            source_site="jobsdb",
            trigger_type="manual",
            request_payload={"category_ids": [6281], "max_pages": 3},
            requested_by="pytest",
        )

        assert crawl_job.status == "queued"
        assert crawl_job.source_site == "jobsdb"
        assert crawl_job.request_payload["max_pages"] == 3

        first_event = repository.append_event(
            db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.requested",
            payload={"page": 1},
            emitted_by="pytest",
        )
        second_event = repository.append_event(
            db,
            crawl_job_id=crawl_job.id,
            event_type="crawl.started",
            payload={"stage": "bootstrap"},
            emitted_by="pytest",
        )

        assert first_event.sequence_no == 1
        assert second_event.sequence_no == 2
    finally:
        db.close()


def test_event_outbox_repository_lists_pending_rows():
    db = _build_sqlite_session()
    try:
        repository = EventOutboxRepository()
        aggregate_id = str(uuid.uuid4())

        row = repository.enqueue(
            db,
            topic="stream.crawl.commands",
            aggregate_type="crawl_job",
            aggregate_id=aggregate_id,
            event_type="crawl.requested",
            payload={"crawl_job_id": aggregate_id},
        )

        pending_rows = repository.list_pending(db, limit=10)

        assert row.status == "pending"
        assert row.aggregate_id == aggregate_id
        assert [item.id for item in pending_rows] == [row.id]
    finally:
        db.close()


def test_crawl_job_events_enforce_per_job_sequence_uniqueness_in_schema():
    unique_constraints = [
        constraint
        for constraint in CrawlJobEvent.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]

    assert any(
        constraint.name == "uq_crawl_job_events_job_sequence"
        for constraint in unique_constraints
    )


def test_record_runtime_event_merges_metrics_without_dropping_existing_keys():
    db = _build_sqlite_session()
    try:
        repository = CrawlJobRepository()
        crawl_job = repository.create_crawl_job(
            db,
            source_site="jobsdb",
            trigger_type="manual",
            request_payload={"category_ids": [6281], "max_pages": 1},
            requested_by="pytest",
        )
        crawl_job.metrics = {
            "ingest_items_seen": 2,
            "ingest_jobs_created": 1,
        }
        db.commit()

        repository.record_runtime_event(
            db,
            crawl_job_id=crawl_job.id,
            status="completed",
            event_type="crawl.completed",
            payload={"status": "completed"},
            metrics={
                "pages_processed": 1,
                "items_emitted": 1,
                "job_ids_collected": 1,
            },
        )

        db.refresh(crawl_job)
        assert crawl_job.metrics == {
            "ingest_items_seen": 2,
            "ingest_jobs_created": 1,
            "pages_processed": 1,
            "items_emitted": 1,
            "job_ids_collected": 1,
        }
    finally:
        db.close()
