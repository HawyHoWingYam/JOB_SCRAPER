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
from app.messaging.topics import STREAM_JOB_EMBEDDING, STREAM_JOB_LIFECYCLE
from app.models import (
    Company,
    EventOutbox,
    Job,
    JobEmbedding,
    JobSkillMention,
    Skill,
    SkillCategory,
    SkillReviewCandidate,
    SkillTechnology,
)
from app.models.job_embedding import EMBEDDING_DIMENSIONS
from app.workers.run_embedding_worker import EmbeddingWorkerService


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


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

    def consume_group(self, topic, group_name, consumer_name, *, count=10, block_ms=1000):
        out = list(self.messages_by_topic.get(topic, []))[:count]
        self.messages_by_topic[topic] = self.messages_by_topic.get(topic, [])[len(out):]
        return out

    def publish(self, topic, envelope):
        serialized = envelope.to_dict()
        self.published.append((topic, serialized))
        return f"{topic}-{len(self.published)}"

    def ack(self, topic, group_name, message_id):
        self.acked.append((topic, group_name, message_id))
        return 1


class FakeEmbeddingModel:
    def __init__(self):
        self.calls = []

    def encode(self, text, normalize_embeddings=True):
        self.calls.append((text, normalize_embeddings))
        vector = [0.0] * EMBEDDING_DIMENSIONS
        vector[0] = float(len(text))
        vector[1] = 1.0
        return vector


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
            EventOutbox.__table__,
            JobEmbedding.__table__,
            SkillCategory.__table__,
            SkillTechnology.__table__,
            Skill.__table__,
            SkillReviewCandidate.__table__,
            JobSkillMention.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _create_job(db):
    company = Company(
        id=uuid.uuid4(),
        company_id=f"company-{uuid.uuid4()}",
        source_site="jobsdb",
        source_company_id=f"source-company-{uuid.uuid4()}",
        name="Acme Health",
    )
    db.add(company)
    db.flush()

    job = Job(
        id=uuid.uuid4(),
        job_id=f"jobsdb:{uuid.uuid4()}",
        source_site="jobsdb",
        source_job_id=f"source-job-{uuid.uuid4()}",
        company_id=company.id,
        title="Platform Engineer",
        description="Build platform tooling",
        source_classification_name="Information & Communication Technology",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    return job


def _lifecycle_message(*, message_id, event_type, job_id, crawl_job_id=None):
    envelope = build_event_envelope(
        event_type=event_type,
        aggregate_type="job",
        aggregate_id=str(job_id),
        source_service="test",
        event_id=f"evt-{message_id}",
        payload={
            "job_id": str(job_id),
            "crawl_job_id": crawl_job_id,
        },
    )
    return FakeMessage(message_id=message_id, event=envelope)


def test_embedding_worker_persists_initial_embedding_for_job_ingested():
    session_factory = _build_sqlite_session_factory()
    db = session_factory()
    try:
        job = _create_job(db)
        job_id = job.id
    finally:
        db.close()

    bus = FakeBus(
        {
            STREAM_JOB_LIFECYCLE: [
                _lifecycle_message(
                    message_id="1-0",
                    event_type="job.ingested",
                    job_id=job_id,
                    crawl_job_id="crawl-1",
                )
            ]
        }
    )
    embedding_model = FakeEmbeddingModel()
    service = EmbeddingWorkerService(
        bus=bus,
        session_factory=session_factory,
        embedding_model=embedding_model,
    )

    processed = asyncio.run(service.run_once())

    assert processed == 1
    assert embedding_model.calls
    assert bus.acked == [(STREAM_JOB_LIFECYCLE, "embedding-workers", "1-0")]
    assert [topic for topic, _ in bus.published] == [STREAM_JOB_EMBEDDING]
    assert bus.published[0][1]["event_type"] == "job.embedded"
    assert bus.published[0][1]["payload"]["trigger_event_type"] == "job.ingested"

    db = session_factory()
    try:
        stored = db.query(JobEmbedding).filter(JobEmbedding.job_id == job_id).one()
        assert stored.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
        assert "Platform Engineer" in stored.document_text
    finally:
        db.close()


def test_embedding_worker_reembeds_job_after_enrichment_when_hash_changes():
    session_factory = _build_sqlite_session_factory()
    db = session_factory()
    try:
        job = _create_job(db)
        job_id = job.id
    finally:
        db.close()

    bus = FakeBus(
        {
            STREAM_JOB_LIFECYCLE: [
                _lifecycle_message(message_id="1-0", event_type="job.ingested", job_id=job_id),
            ]
        }
    )
    embedding_model = FakeEmbeddingModel()
    service = EmbeddingWorkerService(
        bus=bus,
        session_factory=session_factory,
        embedding_model=embedding_model,
    )

    first_processed = asyncio.run(service.run_once())

    db = session_factory()
    try:
        original = db.query(JobEmbedding).filter(JobEmbedding.job_id == job_id).one()
        first_hash = original.document_hash
        job = db.query(Job).filter(Job.id == job_id).one()
        job.ai_summary = "Design the internal developer platform."
        db.commit()
    finally:
        db.close()

    bus.messages_by_topic[STREAM_JOB_LIFECYCLE].append(
        _lifecycle_message(message_id="2-0", event_type="job.enriched", job_id=job_id)
    )
    second_processed = asyncio.run(service.run_once())

    assert first_processed == 1
    assert second_processed == 1
    assert [payload["event_type"] for _, payload in bus.published] == [
        "job.embedded",
        "job.embedded",
    ]
    assert bus.published[-1][1]["payload"]["trigger_event_type"] == "job.enriched"

    db = session_factory()
    try:
        updated = db.query(JobEmbedding).filter(JobEmbedding.job_id == job_id).one()
        assert updated.document_hash != first_hash
        assert "Design the internal developer platform." in updated.document_text
    finally:
        db.close()


def test_embedding_worker_skips_reembedding_when_document_hash_is_unchanged():
    session_factory = _build_sqlite_session_factory()
    db = session_factory()
    try:
        job = _create_job(db)
        job_id = job.id
    finally:
        db.close()

    bus = FakeBus(
        {
            STREAM_JOB_LIFECYCLE: [
                _lifecycle_message(message_id="1-0", event_type="job.ingested", job_id=job_id),
            ]
        }
    )
    embedding_model = FakeEmbeddingModel()
    service = EmbeddingWorkerService(
        bus=bus,
        session_factory=session_factory,
        embedding_model=embedding_model,
    )

    first_processed = asyncio.run(service.run_once())
    bus.messages_by_topic[STREAM_JOB_LIFECYCLE].append(
        _lifecycle_message(message_id="2-0", event_type="job.enriched", job_id=job_id)
    )
    second_processed = asyncio.run(service.run_once())

    assert first_processed == 1
    assert second_processed == 1
    assert [payload["event_type"] for _, payload in bus.published] == ["job.embedded"]
    assert len(embedding_model.calls) == 1


def test_embedding_worker_acks_and_ignores_unrelated_lifecycle_events():
    session_factory = _build_sqlite_session_factory()
    db = session_factory()
    try:
        job = _create_job(db)
        job_id = job.id
    finally:
        db.close()

    bus = FakeBus(
        {
            STREAM_JOB_LIFECYCLE: [
                _lifecycle_message(message_id="1-0", event_type="job.deleted", job_id=job_id),
            ]
        }
    )
    service = EmbeddingWorkerService(
        bus=bus,
        session_factory=session_factory,
        embedding_model=FakeEmbeddingModel(),
    )

    processed = asyncio.run(service.run_once())

    assert processed == 1
    assert bus.published == []
    assert bus.acked == [(STREAM_JOB_LIFECYCLE, "embedding-workers", "1-0")]
