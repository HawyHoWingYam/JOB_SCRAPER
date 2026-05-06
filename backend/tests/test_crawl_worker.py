from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.database import Base
from app.messaging.event_envelope import build_event_envelope
from app.messaging.topics import STREAM_CRAWL_COMMANDS, STREAM_CRAWL_PROGRESS, STREAM_JOB_INGEST
from app.models import CrawlJob, CrawlJobEvent


@dataclass
class FakeMessage:
    message_id: str
    event: object


class FakeBus:
    def __init__(self, messages):
        self.messages = messages
        self.published = []
        self.acked = []

    def ensure_group(self, topic, group_name, start_id="0"):
        return None

    def consume_group(self, topic, group_name, consumer_name, *, count=10, block_ms=1000):
        out = self.messages
        self.messages = []
        return out

    def publish(self, topic, envelope):
        self.published.append((topic, envelope.to_dict()))
        return f"{topic}-1"

    def ack(self, topic, group_name, message_id):
        self.acked.append((topic, group_name, message_id))
        return 1


class FakeRunner:
    def __init__(self):
        self.calls = []

    async def crawl(self, *, crawl_job_id, request_payload, emit_page_processed, emit_item_emitted):
        self.calls.append((crawl_job_id, request_payload))
        emit_page_processed({"current_page": 1, "total_pages": 1, "job_ids_collected": 1})
        emit_item_emitted(
            {
                "source_site": "jobsdb",
                "source_job_id": "123456",
                "source_url": "https://hk.jobsdb.com/job/123456",
                "title": "Senior Data Analyst",
                "description": "Build reports",
                "company_name": "ACME Ltd",
                "location": "Hong Kong",
                "salary_range": "HK$30,000 - HK$40,000",
                "employment_type": "Full-time",
                "source_classification_id": "6281",
                "source_classification_name": "Information & Communication Technology",
                "source_subclassification_id": "6282",
                "source_subclassification_name": "Data Science",
                "posted_date": "2026-05-01T12:00:00+00:00",
                "raw_data": {"jobsdb_id": "123456"},
            }
        )
        return {"pages_processed": 1, "items_emitted": 1}


class FailingRunner:
    async def crawl(self, *, crawl_job_id, request_payload, emit_page_processed, emit_item_emitted):
        raise RuntimeError(f"boom for {crawl_job_id}")


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


def _build_sqlite_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(
        engine,
        tables=[
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _create_crawl_job(session_factory, *, crawl_job_id: str, source_site: str = "jobsdb"):
    db = session_factory()
    try:
        crawl_job = CrawlJob(
            id=uuid.UUID(crawl_job_id),
            source_site=source_site,
            trigger_type="manual",
            status="queued",
            request_payload={"category_ids": [6281], "max_pages": 1},
            requested_by="pytest",
        )
        db.add(crawl_job)
        db.commit()
    finally:
        db.close()


def test_crawl_worker_run_once_routes_requested_event_and_publishes_lifecycle():
    from app.workers.run_crawl_worker import CrawlWorkerService
    session_factory = _build_sqlite_session_factory()
    crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(session_factory, crawl_job_id=crawl_job_id)
    envelope = build_event_envelope(
        event_type="crawl.requested",
        aggregate_type="crawl_job",
        aggregate_id=crawl_job_id,
        source_service="test-suite",
        event_id="evt-1",
        payload={
            "crawl_job_id": crawl_job_id,
            "source_site": "jobsdb",
            "request_payload": {"category_ids": [6281], "max_pages": 1},
        },
    )
    bus = FakeBus([FakeMessage(message_id="1-0", event=envelope)])
    runner = FakeRunner()
    service = CrawlWorkerService(
        bus=bus,
        group_name="crawl-workers",
        consumer_name="worker-1",
        runner_registry={"jobsdb": runner},
        session_factory=session_factory,
    )

    processed = asyncio.run(service.run_once())

    assert processed == 1
    assert runner.calls == [(crawl_job_id, {"category_ids": [6281], "max_pages": 1})]
    assert [topic for topic, _ in bus.published] == [
        STREAM_CRAWL_PROGRESS,
        STREAM_CRAWL_PROGRESS,
        STREAM_JOB_INGEST,
        STREAM_CRAWL_PROGRESS,
    ]
    assert [payload["event_type"] for _, payload in bus.published] == [
        "crawl.started",
        "crawl.page_processed",
        "crawl.item_emitted",
        "crawl.completed",
    ]
    assert bus.acked == [(STREAM_CRAWL_COMMANDS, "crawl-workers", "1-0")]


def test_crawl_worker_persists_success_lifecycle_and_metrics():
    from app.workers.run_crawl_worker import CrawlWorkerService

    session_factory = _build_sqlite_session_factory()
    crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(session_factory, crawl_job_id=crawl_job_id)

    envelope = build_event_envelope(
        event_type="crawl.requested",
        aggregate_type="crawl_job",
        aggregate_id=crawl_job_id,
        source_service="test-suite",
        event_id="evt-success",
        payload={
            "crawl_job_id": crawl_job_id,
            "source_site": "jobsdb",
            "request_payload": {"category_ids": [6281], "max_pages": 1},
        },
    )
    bus = FakeBus([FakeMessage(message_id="1-0", event=envelope)])
    service = CrawlWorkerService(
        bus=bus,
        group_name="crawl-workers",
        consumer_name="worker-1",
        runner_registry={"jobsdb": FakeRunner()},
        session_factory=session_factory,
    )

    asyncio.run(service.run_once())

    db = session_factory()
    try:
        crawl_job = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(crawl_job_id)).one()
        events = (
            db.query(CrawlJobEvent)
            .filter(CrawlJobEvent.crawl_job_id == crawl_job.id)
            .order_by(CrawlJobEvent.sequence_no.asc())
            .all()
        )

        assert crawl_job.status == "completed"
        assert crawl_job.started_at is not None
        assert crawl_job.completed_at is not None
        assert crawl_job.error_message is None
        assert crawl_job.metrics == {
            "pages_processed": 1,
            "items_emitted": 1,
            "job_ids_collected": 1,
        }
        assert [event.event_type for event in events] == [
            "crawl.started",
            "crawl.page_processed",
            "crawl.completed",
        ]
        assert [event.sequence_no for event in events] == [1, 2, 3]
        assert events[1].payload["job_ids_collected"] == 1
        assert bus.published[2][0] == STREAM_JOB_INGEST
        assert bus.published[2][1]["event_type"] == "crawl.item_emitted"
        assert bus.published[2][1]["aggregate_type"] == "crawl_job"
        assert bus.published[2][1]["aggregate_id"] == crawl_job_id
        assert bus.published[2][1]["source_service"] == "crawl-worker"
        assert bus.published[2][1]["schema_version"] == 1
        assert bus.published[2][1]["payload"] == {
            "crawl_job_id": crawl_job_id,
            "source_site": "jobsdb",
            "job": {
                "source_site": "jobsdb",
                "source_job_id": "123456",
                "source_url": "https://hk.jobsdb.com/job/123456",
                "title": "Senior Data Analyst",
                "description": "Build reports",
                "company_name": "ACME Ltd",
                "location": "Hong Kong",
                "salary_range": "HK$30,000 - HK$40,000",
                "employment_type": "Full-time",
                "source_classification_id": "6281",
                "source_classification_name": "Information & Communication Technology",
                "source_subclassification_id": "6282",
                "source_subclassification_name": "Data Science",
                "posted_date": "2026-05-01T12:00:00+00:00",
                "raw_data": {"jobsdb_id": "123456"},
            },
        }
    finally:
        db.close()


def test_crawl_worker_persists_failed_lifecycle():
    from app.workers.run_crawl_worker import CrawlWorkerService

    session_factory = _build_sqlite_session_factory()
    crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(session_factory, crawl_job_id=crawl_job_id)

    envelope = build_event_envelope(
        event_type="crawl.requested",
        aggregate_type="crawl_job",
        aggregate_id=crawl_job_id,
        source_service="test-suite",
        event_id="evt-failure",
        payload={
            "crawl_job_id": crawl_job_id,
            "source_site": "jobsdb",
            "request_payload": {"category_ids": [6281], "max_pages": 1},
        },
    )
    bus = FakeBus([FakeMessage(message_id="1-0", event=envelope)])
    service = CrawlWorkerService(
        bus=bus,
        group_name="crawl-workers",
        consumer_name="worker-1",
        runner_registry={"jobsdb": FailingRunner()},
        session_factory=session_factory,
    )

    asyncio.run(service.run_once())

    db = session_factory()
    try:
        crawl_job = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(crawl_job_id)).one()
        events = (
            db.query(CrawlJobEvent)
            .filter(CrawlJobEvent.crawl_job_id == crawl_job.id)
            .order_by(CrawlJobEvent.sequence_no.asc())
            .all()
        )

        assert crawl_job.status == "failed"
        assert crawl_job.started_at is not None
        assert crawl_job.completed_at is not None
        assert crawl_job.error_message == f"boom for {crawl_job_id}"
        assert crawl_job.metrics == {
            "pages_processed": 0,
            "items_emitted": 0,
            "job_ids_collected": 0,
        }
        assert [event.event_type for event in events] == [
            "crawl.started",
            "crawl.failed",
        ]
        assert events[1].payload["error"] == f"boom for {crawl_job_id}"
    finally:
        db.close()
