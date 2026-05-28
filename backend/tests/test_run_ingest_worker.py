from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID
from uuid import uuid4

from app.messaging.event_envelope import build_event_envelope
from app.workers.run_ingest_worker import (
    INGEST_ITEM_SETTLED_EVENT_TYPE,
    IngestWorkerService,
    InvalidIngestPayloadError,
)


class FakeBus:
    def __init__(self) -> None:
        self.ensure_group_calls: list[tuple] = []
        self.consume_group_calls: list[dict[str, object]] = []

    def ensure_group(self, *args, **kwargs) -> None:
        self.ensure_group_calls.append((args, kwargs))

    def consume_group(self, topic, group_name, consumer_name, *, count=10, block_ms=100, reclaim_idle_ms=None):
        self.consume_group_calls.append(
            {
                "topic": topic,
                "group_name": group_name,
                "consumer_name": consumer_name,
                "count": count,
                "block_ms": block_ms,
                "reclaim_idle_ms": reclaim_idle_ms,
            }
        )
        return []


def test_ingest_worker_attempts_to_reclaim_stale_pending_messages_before_waiting_for_new_work():
    bus = FakeBus()
    service = IngestWorkerService(bus=bus)

    processed = asyncio.run(service.run_once())

    assert processed == 0
    assert bus.consume_group_calls == [
        {
            "topic": "stream.job.ingest",
            "group_name": "ingest-workers",
            "consumer_name": "ingest-worker",
            "count": 10,
            "block_ms": 100,
            "reclaim_idle_ms": 60_000,
        }
    ]


class FakeCompanyRepository:
    def upsert_company(self, db, company_data, auto_commit=False):
        return SimpleNamespace(id=uuid4()), "created"


class FakeJobRepository:
    def __init__(self, *, action: str) -> None:
        self.action = action

    def upsert_source_job(self, db, job_data, skip_existing=False, auto_commit=False):
        return SimpleNamespace(id=uuid4(), job_id=job_data["job_id"]), self.action


class FakeCrawlJobRepository:
    def __init__(self) -> None:
        self.increment_calls: list[dict[str, object]] = []
        self.append_calls: list[dict[str, object]] = []

    def get_crawl_job_by_id(self, db, crawl_job_id):
        return SimpleNamespace(request_payload={"skip_existing": False})

    def increment_metrics(self, db, *, crawl_job_id, metrics_delta, auto_commit=False):
        self.increment_calls.append(
            {
                "crawl_job_id": crawl_job_id,
                "metrics_delta": metrics_delta,
                "auto_commit": auto_commit,
            }
        )

    def append_event(self, db, *, crawl_job_id, event_type, payload, emitted_by=None, auto_commit=False):
        self.append_calls.append(
            {
                "crawl_job_id": crawl_job_id,
                "event_type": event_type,
                "payload": payload,
                "emitted_by": emitted_by,
                "auto_commit": auto_commit,
            }
        )


class FakeListingRepository:
    def attach_published_job(self, db, *, listing_id, published_job_id, auto_commit=False):
        return None


class FakeEventOutboxRepository:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, object]] = []

    def enqueue(self, db, **kwargs):
        self.enqueued.append(kwargs)


def _build_ingest_event():
    return build_event_envelope(
        event_type="crawl.item_emitted",
        aggregate_type="crawl_job",
        aggregate_id=str(uuid4()),
        source_service="crawl-worker",
        payload={
            "crawl_job_id": str(uuid4()),
            "source_site": "ctgoodjobs",
            "job": {
                "source_site": "ctgoodjobs",
                "source_job_id": "10115418",
                "source_url": "https://jobs.ctgoodjobs.hk/job/10115418/customer-platform-engineering-consultant",
                "title": "Customer Platform Engineering, Consultant",
                "description": "desc",
                "company_name": "Example Co",
                "location": "Hong Kong",
                "employment_type": "Full time",
                "source_classification_id": "ctgoodjobs:021",
                "source_classification_name": "Information Technology",
                "raw_data": {
                    "source_site": "ctgoodjobs",
                    "job_id": "10115418",
                    "company_name": "Example Co",
                },
            },
        },
    )


def test_ingest_worker_records_settled_event_for_successful_ingest():
    crawl_job_repository = FakeCrawlJobRepository()
    event_outbox_repository = FakeEventOutboxRepository()
    service = IngestWorkerService(
        bus=FakeBus(),
        crawl_job_listing_repository=FakeListingRepository(),
        company_repository=FakeCompanyRepository(),
        crawl_job_repository=crawl_job_repository,
        event_outbox_repository=event_outbox_repository,
        job_repository=FakeJobRepository(action="created"),
        session_factory=lambda: None,
    )

    result = service._persist_event(object(), _build_ingest_event())

    assert result.action == "created"
    assert crawl_job_repository.append_calls == [
        {
            "crawl_job_id": UUID(result.crawl_job_id),
            "event_type": INGEST_ITEM_SETTLED_EVENT_TYPE,
            "payload": {
                "source_site": "ctgoodjobs",
                "source_job_id": "10115418",
                "job_id": result.job_id,
                "action": "created",
            },
            "emitted_by": "ingest-worker",
            "auto_commit": False,
        }
    ]


def test_ingest_worker_records_settled_event_for_dead_lettered_ingest():
    crawl_job_repository = FakeCrawlJobRepository()
    service = IngestWorkerService(
        bus=FakeBus(),
        crawl_job_repository=crawl_job_repository,
        session_factory=lambda: None,
    )
    event = _build_ingest_event()
    failure = InvalidIngestPayloadError("missing_job_content", "Missing content")

    service._record_ingest_failure(object(), event, failure)

    assert len(crawl_job_repository.append_calls) == 1
    append_call = crawl_job_repository.append_calls[0]
    assert append_call["event_type"] == INGEST_ITEM_SETTLED_EVENT_TYPE
    assert append_call["payload"] == {
        "source_site": "ctgoodjobs",
        "source_job_id": "10115418",
        "action": "dead_lettered",
        "reason": "missing_job_content",
    }
    assert append_call["emitted_by"] == "ingest-worker"
    assert append_call["auto_commit"] is False
