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
from app.messaging.topics import STREAM_JOB_INGEST, STREAM_JOB_LIFECYCLE
from app.models import Company, CrawlJob, CrawlJobEvent, EventOutbox, Job
from app.workers.run_ingest_worker import IngestWorkerService


STREAM_JOB_INGEST_DEAD_LETTER = "stream.job.ingest.dead_letter"


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

    def consume_group(
        self,
        topic,
        group_name,
        consumer_name,
        *,
        count=10,
        block_ms=1000,
        stream_id=">",
    ):
        out = self.messages
        self.messages = []
        return out

    def publish(self, topic, envelope):
        self.published.append((topic, envelope.to_dict()))
        return f"{topic}-{len(self.published)}"

    def ack(self, topic, group_name, message_id):
        self.acked.append((topic, group_name, message_id))
        return 1


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
            Company.__table__,
            Job.__table__,
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
            EventOutbox.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _create_crawl_job(
    session_factory,
    *,
    crawl_job_id: str,
    source_site: str = "jobsdb",
    metrics: dict | None = None,
):
    db = session_factory()
    try:
        crawl_job = CrawlJob(
            id=uuid.UUID(crawl_job_id),
            source_site=source_site,
            trigger_type="manual",
            status="completed",
            request_payload={"category_ids": [6281], "max_pages": 1},
            requested_by="pytest",
            metrics=metrics or {},
        )
        db.add(crawl_job)
        db.commit()
    finally:
        db.close()


def _canonical_jobsdb_payload():
    return {
        "source_site": "jobsdb",
        "source_job_id": "91890673",
        "source_url": "https://hk.jobsdb.com/job/91890673",
        "title": "Senior Data Analyst",
        "description": "Build reporting pipelines",
        "company_name": "ACME Ltd",
        "location": "Hong Kong",
        "salary_range": "HK$30,000 - HK$40,000",
        "employment_type": "Full-time",
        "source_classification_id": "6281",
        "source_classification_name": "Information & Communication Technology",
        "source_subclassification_id": "6282",
        "source_subclassification_name": "Data Science",
        "posted_date": "2026-05-01T12:00:00+00:00",
        "raw_data": {
            "jobsdb_id": "91890673",
            "advertiser_id": "61347806",
            "advertiser_name": "ACME Ltd",
        },
    }


def _canonical_ctgoodjobs_payload():
    return {
        "source_site": "ctgoodjobs",
        "source_job_id": "10070449",
        "source_url": "https://jobs.ctgoodjobs.hk/job/10070449",
        "title": "Enterprise Architect",
        "description": "Own enterprise application architecture.",
        "company_name": "ConnectedGroup Limited",
        "location": "Central and Western District",
        "salary_range": "N/A",
        "employment_type": "Full-time",
        "source_classification_id": "ctgoodjobs:021",
        "source_classification_name": "Information Technology",
        "source_subclassification_id": None,
        "source_subclassification_name": None,
        "posted_date": "2026-04-15",
        "raw_data": {
            "source_site": "ctgoodjobs",
            "job_id": "10070449",
            "company_name": "ConnectedGroup Limited",
            "description_text": "Own enterprise application architecture.",
            "errors": [],
        },
    }


def test_ingest_worker_persists_job_emits_lifecycle_and_merges_metrics():
    session_factory = _build_sqlite_session_factory()
    crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(
        session_factory,
        crawl_job_id=crawl_job_id,
        metrics={
            "pages_processed": 1,
            "items_emitted": 1,
            "job_ids_collected": 1,
        },
    )

    envelope = build_event_envelope(
        event_type="crawl.item_emitted",
        aggregate_type="crawl_job",
        aggregate_id=crawl_job_id,
        source_service="crawl-worker",
        event_id="evt-ingest-1",
        payload={
            "crawl_job_id": crawl_job_id,
            "source_site": "jobsdb",
            "job": _canonical_jobsdb_payload(),
        },
    )
    bus = FakeBus([FakeMessage(message_id="1-0", event=envelope)])
    service = IngestWorkerService(
        bus=bus,
        group_name="ingest-workers",
        consumer_name="worker-1",
        session_factory=session_factory,
    )

    processed = asyncio.run(service.run_once())

    assert processed == 1
    assert bus.acked == [(STREAM_JOB_INGEST, "ingest-workers", "1-0")]
    assert [topic for topic, _ in bus.published] == [STREAM_JOB_LIFECYCLE]
    assert bus.published[0][1]["event_type"] == "job.ingested"
    assert bus.published[0][1]["source_service"] == "ingest-worker"
    assert bus.published[0][1]["payload"]["action"] == "created"
    assert bus.published[0][1]["payload"]["source_job_id"] == "91890673"

    db = session_factory()
    try:
        companies = db.query(Company).all()
        jobs = db.query(Job).all()
        crawl_job = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(crawl_job_id)).one()

        assert len(companies) == 1
        assert companies[0].source_site == "jobsdb"
        assert companies[0].source_company_id == "61347806"
        assert len(jobs) == 1
        assert jobs[0].source_site == "jobsdb"
        assert jobs[0].source_job_id == "91890673"
        assert crawl_job.metrics == {
            "pages_processed": 1,
            "items_emitted": 1,
            "job_ids_collected": 1,
            "ingest_items_seen": 1,
            "ingest_jobs_created": 1,
        }
    finally:
        db.close()


def test_ingest_worker_skips_duplicate_replays_without_emitting_duplicate_lifecycle():
    session_factory = _build_sqlite_session_factory()
    crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(session_factory, crawl_job_id=crawl_job_id)

    payload = {
        "crawl_job_id": crawl_job_id,
        "source_site": "jobsdb",
        "job": _canonical_jobsdb_payload(),
    }
    first = build_event_envelope(
        event_type="crawl.item_emitted",
        aggregate_type="crawl_job",
        aggregate_id=crawl_job_id,
        source_service="crawl-worker",
        event_id="evt-ingest-1",
        payload=payload,
    )
    second = build_event_envelope(
        event_type="crawl.item_emitted",
        aggregate_type="crawl_job",
        aggregate_id=crawl_job_id,
        source_service="crawl-worker",
        event_id="evt-ingest-2",
        payload=payload,
    )
    bus = FakeBus(
        [
            FakeMessage(message_id="1-0", event=first),
            FakeMessage(message_id="2-0", event=second),
        ]
    )
    service = IngestWorkerService(
        bus=bus,
        group_name="ingest-workers",
        consumer_name="worker-1",
        session_factory=session_factory,
    )

    processed = asyncio.run(service.run_once())

    assert processed == 2
    assert [topic for topic, _ in bus.published] == [STREAM_JOB_LIFECYCLE]

    db = session_factory()
    try:
        jobs = db.query(Job).all()
        crawl_job = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(crawl_job_id)).one()

        assert len(jobs) == 1
        assert crawl_job.metrics == {
            "ingest_items_seen": 2,
            "ingest_jobs_created": 1,
            "ingest_jobs_skipped": 1,
        }
    finally:
        db.close()


def test_ingest_worker_normalizes_jobsdb_salary_objects_before_persisting():
    session_factory = _build_sqlite_session_factory()
    crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(session_factory, crawl_job_id=crawl_job_id)

    payload = _canonical_jobsdb_payload()
    payload["salary_range"] = {
        "__typename": "JobSalary",
        "currencyLabel": None,
        "label": "$11,490 per month",
    }

    envelope = build_event_envelope(
        event_type="crawl.item_emitted",
        aggregate_type="crawl_job",
        aggregate_id=crawl_job_id,
        source_service="crawl-worker",
        event_id="evt-ingest-salary-object",
        payload={
            "crawl_job_id": crawl_job_id,
            "source_site": "jobsdb",
            "job": payload,
        },
    )
    bus = FakeBus([FakeMessage(message_id="1-0", event=envelope)])
    service = IngestWorkerService(
        bus=bus,
        group_name="ingest-workers",
        consumer_name="worker-1",
        session_factory=session_factory,
    )

    processed = asyncio.run(service.run_once())

    assert processed == 1

    db = session_factory()
    try:
        job = db.query(Job).one()
        assert job.salary_range == "$11,490 per month"
        assert job.salary_min == 11490
        assert job.salary_max == 11490
    finally:
        db.close()


def test_ingest_worker_dead_letters_malformed_ctgoodjobs_payload_and_continues():
    session_factory = _build_sqlite_session_factory()
    bad_crawl_job_id = str(uuid.uuid4())
    valid_crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(session_factory, crawl_job_id=bad_crawl_job_id, source_site="ctgoodjobs")
    _create_crawl_job(session_factory, crawl_job_id=valid_crawl_job_id)

    malformed = build_event_envelope(
        event_type="crawl.item_emitted",
        aggregate_type="crawl_job",
        aggregate_id=bad_crawl_job_id,
        source_service="crawl-worker",
        event_id="evt-ingest-bad",
        payload={
            "crawl_job_id": bad_crawl_job_id,
            "source_site": "ctgoodjobs",
            "job": {
                "source_site": "ctgoodjobs",
                "source_job_id": "10104982",
                "source_url": "https://jobs.ctgoodjobs.hk/job/10104982",
                "title": "",
                "description": None,
                "company_name": None,
                "raw_data": {
                    "errors": ["missing_job_content"],
                    "field_coverage": {"required_total": 16, "required_present": 4},
                },
            },
        },
    )
    valid = build_event_envelope(
        event_type="crawl.item_emitted",
        aggregate_type="crawl_job",
        aggregate_id=valid_crawl_job_id,
        source_service="crawl-worker",
        event_id="evt-ingest-valid",
        payload={
            "crawl_job_id": valid_crawl_job_id,
            "source_site": "jobsdb",
            "job": _canonical_jobsdb_payload(),
        },
    )
    bus = FakeBus(
        [
            FakeMessage(message_id="1-0", event=malformed),
            FakeMessage(message_id="2-0", event=valid),
        ]
    )
    service = IngestWorkerService(
        bus=bus,
        group_name="ingest-workers",
        consumer_name="worker-1",
        session_factory=session_factory,
    )

    processed = asyncio.run(service.run_once())

    assert processed == 2
    assert bus.acked == [
        (STREAM_JOB_INGEST, "ingest-workers", "1-0"),
        (STREAM_JOB_INGEST, "ingest-workers", "2-0"),
    ]
    assert [topic for topic, _ in bus.published] == [
        STREAM_JOB_INGEST_DEAD_LETTER,
        STREAM_JOB_LIFECYCLE,
    ]
    dead_letter = bus.published[0][1]
    assert dead_letter["event_type"] == "ingest.message_dead_lettered"
    assert dead_letter["payload"]["reason"] == "missing_job_content"
    assert dead_letter["payload"]["original_event_id"] == "evt-ingest-bad"

    db = session_factory()
    try:
        bad_crawl_job = db.query(CrawlJob).filter(CrawlJob.id == uuid.UUID(bad_crawl_job_id)).one()
        assert bad_crawl_job.metrics["ingest_items_failed"] == 1
        assert bad_crawl_job.metrics["ingest_dead_lettered"] == 1
        assert bad_crawl_job.metrics["ingest_failure_missing_job_content"] == 1
        assert db.query(Job).count() == 1
    finally:
        db.close()


def test_ingest_worker_derives_fallback_company_identity_from_company_name():
    session_factory = _build_sqlite_session_factory()
    crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(session_factory, crawl_job_id=crawl_job_id, source_site="ctgoodjobs")

    payload = _canonical_ctgoodjobs_payload()
    payload["raw_data"].pop("company_id", None)

    envelope = build_event_envelope(
        event_type="crawl.item_emitted",
        aggregate_type="crawl_job",
        aggregate_id=crawl_job_id,
        source_service="crawl-worker",
        event_id="evt-ingest-fallback-company",
        payload={
            "crawl_job_id": crawl_job_id,
            "source_site": "ctgoodjobs",
            "job": payload,
        },
    )
    bus = FakeBus([FakeMessage(message_id="1-0", event=envelope)])
    service = IngestWorkerService(
        bus=bus,
        group_name="ingest-workers",
        consumer_name="worker-1",
        session_factory=session_factory,
    )

    processed = asyncio.run(service.run_once())

    assert processed == 1
    assert [topic for topic, _ in bus.published] == [STREAM_JOB_LIFECYCLE]

    db = session_factory()
    try:
        company = db.query(Company).one()
        job = db.query(Job).one()
        assert company.source_site == "ctgoodjobs"
        assert company.source_company_id.startswith("fallback:name:")
        assert company.company_id.startswith("ctgoodjobs:fallback:name:")
        assert company.name == "ConnectedGroup Limited"
        assert job.source_site == "ctgoodjobs"
        assert job.source_job_id == "10070449"
    finally:
        db.close()
