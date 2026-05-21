from __future__ import annotations

import asyncio
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
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
from app.messaging.topics import STREAM_CRAWL_PROGRESS, STREAM_JOB_LIFECYCLE
from app.models import AppRuntimeSettings, CrawlJob, EnrichmentRun, EnrichmentRunItem, EventOutbox, Job
from app.services.ai_runtime_settings_service import AIRuntimeSettingsService
from app.services.enrichment_run_service import EnrichmentRunService


@dataclass
class FakeMessage:
    message_id: str
    event: object


class FakeBus:
    def __init__(self, messages_by_topic):
        self.messages_by_topic = {
            topic: list(messages)
            for topic, messages in messages_by_topic.items()
        }
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
    ):
        out = list(self.messages_by_topic.get(topic, []))[:count]
        self.messages_by_topic[topic] = self.messages_by_topic.get(topic, [])[len(out):]
        return out

    def publish(self, topic, envelope):
        serialized = envelope.to_dict()
        self.published.append((topic, serialized))
        queue = self.messages_by_topic.setdefault(topic, [])
        queue.append(
            FakeMessage(
                message_id=f"{topic}-{len(self.published)}",
                event=envelope,
            )
        )
        return f"{topic}-{len(self.published)}"

    def ack(self, topic, group_name, message_id):
        self.acked.append((topic, group_name, message_id))
        return 1


class RecordingEnrichmentService:
    def __init__(self):
        self.calls = []

    async def enrich_job_id(self, job_id):
        self.calls.append(str(job_id))
        return {"job_id": str(job_id), "status": "success"}


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
            AppRuntimeSettings.__table__,
            Job.__table__,
            CrawlJob.__table__,
            EnrichmentRun.__table__,
            EnrichmentRunItem.__table__,
            EventOutbox.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _create_job(db, *, title, created_at):
    job = Job(
        id=uuid.uuid4(),
        job_id=str(uuid.uuid4()),
        source_site="jobsdb",
        source_job_id=str(uuid.uuid4()),
        company_id=uuid.uuid4(),
        title=title,
        description="Test Description",
        source_classification_id="6281",
        source_classification_name="Information & Communication Technology",
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(job)
    db.commit()
    return job


def _create_crawl_job(session_factory, *, crawl_job_id, status="completed", metrics=None):
    db = session_factory()
    try:
        crawl_job = CrawlJob(
            id=uuid.UUID(crawl_job_id),
            source_site="jobsdb",
            trigger_type="manual",
            status=status,
            request_payload={"category_ids": [6281], "max_pages": 1},
            requested_by="pytest",
            metrics=metrics or {},
        )
        db.add(crawl_job)
        db.commit()
    finally:
        db.close()


def _mark_jobs_profile_ready(session_factory):
    db = session_factory()
    try:
        service = AIRuntimeSettingsService(db)
        service.update_settings({"llm_provider": "mock"})
        fingerprint = service.build_config_fingerprint("jobs", service._row_values(service.get_or_create()))
        service.record_profile_test_result(
            "jobs",
            ok=True,
            configured_provider="mock",
            model=None,
            latency_ms=1,
            config_fingerprint=fingerprint,
            error_message=None,
        )
        db.commit()
    finally:
        db.close()


def _job_ingested_message(*, message_id, crawl_job_id, job_id):
    envelope = build_event_envelope(
        event_type="job.ingested",
        aggregate_type="job",
        aggregate_id=str(job_id),
        source_service="ingest-worker",
        event_id=f"evt-{message_id}",
        payload={
            "crawl_job_id": crawl_job_id,
            "job_id": str(job_id),
            "source_site": "jobsdb",
            "source_job_id": f"source-{job_id}",
            "action": "created",
        },
    )
    return FakeMessage(message_id=message_id, event=envelope)


def test_enrichment_worker_aggregates_crawl_auto_run_and_executes_after_dispatch():
    from app.workers.run_enrichment_worker import EnrichmentWorkerService

    session_factory = _build_sqlite_session_factory()
    db = session_factory()
    try:
        first_job = _create_job(
            db,
            title="Worker Auto Job 1",
            created_at=datetime(2026, 5, 5, 15, 0, 0),
        )
        second_job = _create_job(
            db,
            title="Worker Auto Job 2",
            created_at=datetime(2026, 5, 5, 15, 1, 0),
        )
        first_job_id = first_job.id
        second_job_id = second_job.id
    finally:
        db.close()

    crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(
        session_factory,
        crawl_job_id=crawl_job_id,
        status="completed",
        metrics={"items_emitted": 2, "ingest_items_seen": 2},
    )
    _mark_jobs_profile_ready(session_factory)

    bus = FakeBus(
        {
            STREAM_JOB_LIFECYCLE: [
                _job_ingested_message(
                    message_id="1-0",
                    crawl_job_id=crawl_job_id,
                    job_id=first_job_id,
                ),
                _job_ingested_message(
                    message_id="2-0",
                    crawl_job_id=crawl_job_id,
                    job_id=second_job_id,
                ),
            ],
            STREAM_CRAWL_PROGRESS: [],
        }
    )
    enrichment_service = RecordingEnrichmentService()
    service = EnrichmentWorkerService(
        bus=bus,
        session_factory=session_factory,
        enrichment_service=enrichment_service,
    )

    first_processed = asyncio.run(service.run_once())
    second_processed = asyncio.run(service.run_once())

    assert first_processed == 2
    assert second_processed == 1
    assert [payload["event_type"] for _, payload in bus.published] == [
        "enrichment.run.requested",
        "job.enriched",
        "job.enriched",
    ]
    assert enrichment_service.calls == [str(first_job_id), str(second_job_id)]

    db = session_factory()
    try:
        run = db.query(EnrichmentRun).one()
        assert run.source_type == "crawl_auto"
        assert str(run.trigger_crawl_job_id) == crawl_job_id
        assert run.status == "completed"
        assert run.completed_items == 2
        assert run.failed_items == 0

        items = (
            db.query(EnrichmentRunItem)
            .filter(EnrichmentRunItem.run_id == run.id)
            .order_by(EnrichmentRunItem.position.asc())
            .all()
        )
        assert [item.status for item in items] == ["completed", "completed"]
    finally:
        db.close()


def test_enrichment_worker_acks_late_job_ingested_for_terminal_crawl_auto_run():
    from app.workers.run_enrichment_worker import EnrichmentWorkerService

    session_factory = _build_sqlite_session_factory()
    crawl_job_id = str(uuid.uuid4())
    _create_crawl_job(
        session_factory,
        crawl_job_id=crawl_job_id,
        status="completed",
        metrics={"items_emitted": 2, "ingest_items_seen": 2},
    )

    db = session_factory()
    try:
        original_job = _create_job(
            db,
            title="Original Worker Auto Job",
            created_at=datetime(2026, 5, 5, 15, 0, 0),
        )
        late_job = _create_job(
            db,
            title="Late Worker Auto Job",
            created_at=datetime(2026, 5, 5, 15, 1, 0),
        )
        append_result = EnrichmentRunService(db).append_job_to_crawl_auto_run(
            crawl_job_id=crawl_job_id,
            job_id=str(original_job.id),
        )
        append_result.run.status = "failed"
        db.commit()
        late_job_id = late_job.id
    finally:
        db.close()

    bus = FakeBus(
        {
            STREAM_JOB_LIFECYCLE: [
                _job_ingested_message(
                    message_id="1-0",
                    crawl_job_id=crawl_job_id,
                    job_id=late_job_id,
                ),
            ],
            STREAM_CRAWL_PROGRESS: [],
        }
    )
    service = EnrichmentWorkerService(
        bus=bus,
        session_factory=session_factory,
        enrichment_service=RecordingEnrichmentService(),
    )

    processed = asyncio.run(service.run_once())

    assert processed == 1
    assert bus.acked == [(STREAM_JOB_LIFECYCLE, "enrichment-workers", "1-0")]
    assert bus.published == []
