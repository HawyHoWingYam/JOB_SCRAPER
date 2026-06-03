from __future__ import annotations

from datetime import UTC, datetime
import asyncio
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.messaging.event_envelope import build_event_envelope
from app.messaging.topics import STREAM_CRAWL_PROGRESS
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.models.crawl_job_listing import CrawlJobListing
from app.models.schedule import ScrapeSchedule
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.scraper.manual_action import ManualActionRequiredError
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService
from app.workers.run_crawl_worker import CrawlWorkerService


class FakeBus:
    def __init__(self) -> None:
        self.published: list[tuple[str, object]] = []
        self.acked: list[tuple[object, ...]] = []
        self.consume_group_calls: list[dict[str, object]] = []

    def ensure_group(self, *_args, **_kwargs) -> None:
        return None

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

    def publish(self, topic, envelope) -> None:
        self.published.append((topic, envelope))

    def ack(self, *args) -> None:
        self.acked.append(args)


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
            CrawlJobEvent.__table__,
            CrawlJobListing.__table__,
        ],
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_crawl_worker_attempts_to_reclaim_stale_pending_messages_before_waiting_for_new_work():
    bus = FakeBus()
    worker = CrawlWorkerService(bus=bus)

    processed = asyncio.run(worker.run_once())

    assert processed == 0
    assert bus.consume_group_calls == [
        {
            "topic": "stream.crawl.commands",
            "group_name": "crawl-workers",
            "consumer_name": "crawl-worker",
            "count": 10,
            "block_ms": 100,
            "reclaim_idle_ms": 60_000,
        }
    ]


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
    source_site: str = "jobsdb",
    source_job_id: str,
    detail_status: str,
    category_id: str = "1200",
    listing_rank: int,
) -> CrawlJobListing:
    listing = CrawlJobListing(
        crawl_job_id=crawl_job_id,
        source_site=source_site,
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


def test_build_manual_request_payload_defaults_ctgoodjobs_to_headed():
    service = CrawlJobDispatchService()

    payload = service.build_manual_request_payload(
        source_site="ctgoodjobs",
        crawl_phase="listing",
        category_ids=["ctgoodjobs:021"],
        max_pages=2,
    )

    assert payload["crawl_mode"] == "headed"


def test_build_manual_request_payload_upgrades_ctgoodjobs_headless_requests_to_headed():
    service = CrawlJobDispatchService()

    payload = service.build_manual_request_payload(
        source_site="ctgoodjobs",
        crawl_phase="listing",
        crawl_mode="headless",
        category_ids=["ctgoodjobs:021"],
        max_pages=2,
    )

    assert payload["crawl_mode"] == "headed"


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


def test_persist_listing_batch_skips_jobs_already_published_or_staged_in_other_batches():
    session_factory = _build_session_factory()
    db = session_factory()
    existing_listing_batch = _create_crawl_job(
        db,
        request_payload={"crawl_phase": "listing", "source_site": "jobsdb"},
    )
    current_listing_batch = _create_crawl_job(
        db,
        request_payload={"crawl_phase": "listing", "source_site": "jobsdb", "skip_existing": True},
    )

    _create_listing(
        db,
        crawl_job_id=existing_listing_batch.id,
        source_job_id="already-staged",
        detail_status="pending",
        listing_rank=1,
    )

    current_listing_batch_id = current_listing_batch.id
    db.close()

    worker = CrawlWorkerService(
        bus=FakeBus(),
        runner_registry={},
        job_repository=FakeJobRepository(
            existing_by_source_job_id={
                "already-published": SimpleNamespace(id=uuid4()),
            }
        ),
        session_factory=session_factory,
    )

    worker._persist_listing_batch(
        crawl_job_id=str(current_listing_batch_id),
        payloads=[
            {
                "source_site": "jobsdb",
                "source_job_id": "brand-new",
                "source_url": "https://example.test/jobs/brand-new",
                "source_classification_id": "1200",
                "source_classification_name": "Engineering",
                "listing_page": 1,
                "listing_rank": 1,
                "listing_payload": {"source_job_id": "brand-new"},
            },
            {
                "source_site": "jobsdb",
                "source_job_id": "already-staged",
                "source_url": "https://example.test/jobs/already-staged",
                "source_classification_id": "1200",
                "source_classification_name": "Engineering",
                "listing_page": 1,
                "listing_rank": 2,
                "listing_payload": {"source_job_id": "already-staged"},
            },
            {
                "source_site": "jobsdb",
                "source_job_id": "already-published",
                "source_url": "https://example.test/jobs/already-published",
                "source_classification_id": "1200",
                "source_classification_name": "Engineering",
                "listing_page": 1,
                "listing_rank": 3,
                "listing_payload": {"source_job_id": "already-published"},
            },
        ],
        skip_existing=True,
    )

    verification_db = session_factory()
    crawl_job_repository = CrawlJobRepository()
    refreshed_listing_job = crawl_job_repository.get_crawl_job_by_id(
        verification_db,
        current_listing_batch_id,
    )
    current_batch_rows = (
        verification_db.query(CrawlJobListing)
        .filter(CrawlJobListing.crawl_job_id == current_listing_batch_id)
        .order_by(CrawlJobListing.listing_rank.asc())
        .all()
    )
    staged_rows = (
        verification_db.query(CrawlJobListing)
        .filter(CrawlJobListing.source_job_id == "already-staged")
        .order_by(CrawlJobListing.created_at.asc())
        .all()
    )

    assert [row.source_job_id for row in current_batch_rows] == ["brand-new"]
    assert refreshed_listing_job.metrics["jobs_skipped_existing"] == 2
    assert refreshed_listing_job.metrics["listings_staged"] == 1
    assert refreshed_listing_job.metrics["detail_pending"] == 1
    assert len(staged_rows) == 1
    verification_db.close()


def test_persist_listing_batch_applies_cross_batch_skip_existing_to_ctgoodjobs_too():
    session_factory = _build_session_factory()
    db = session_factory()
    existing_listing_batch = _create_crawl_job(
        db,
        source_site="ctgoodjobs",
        request_payload={"crawl_phase": "listing", "source_site": "ctgoodjobs"},
    )
    current_listing_batch = _create_crawl_job(
        db,
        source_site="ctgoodjobs",
        request_payload={"crawl_phase": "listing", "source_site": "ctgoodjobs", "skip_existing": True},
    )

    _create_listing(
        db,
        crawl_job_id=existing_listing_batch.id,
        source_site="ctgoodjobs",
        source_job_id="ctgoodjobs-staged",
        detail_status="pending",
        category_id="ctgoodjobs:021",
        listing_rank=1,
    )

    current_listing_batch_id = current_listing_batch.id
    db.close()

    worker = CrawlWorkerService(
        bus=FakeBus(),
        runner_registry={},
        job_repository=FakeJobRepository(
            existing_by_source_job_id={
                "ctgoodjobs-published": SimpleNamespace(id=uuid4()),
            }
        ),
        session_factory=session_factory,
    )

    worker._persist_listing_batch(
        crawl_job_id=str(current_listing_batch_id),
        payloads=[
            {
                "source_site": "ctgoodjobs",
                "source_job_id": "ctgoodjobs-new",
                "source_url": "https://example.test/jobs/ctgoodjobs-new",
                "source_classification_id": "ctgoodjobs:021",
                "source_classification_name": "Information Technology",
                "listing_page": 1,
                "listing_rank": 1,
                "listing_payload": {"source_job_id": "ctgoodjobs-new"},
            },
            {
                "source_site": "ctgoodjobs",
                "source_job_id": "ctgoodjobs-staged",
                "source_url": "https://example.test/jobs/ctgoodjobs-staged",
                "source_classification_id": "ctgoodjobs:021",
                "source_classification_name": "Information Technology",
                "listing_page": 1,
                "listing_rank": 2,
                "listing_payload": {"source_job_id": "ctgoodjobs-staged"},
            },
            {
                "source_site": "ctgoodjobs",
                "source_job_id": "ctgoodjobs-published",
                "source_url": "https://example.test/jobs/ctgoodjobs-published",
                "source_classification_id": "ctgoodjobs:021",
                "source_classification_name": "Information Technology",
                "listing_page": 1,
                "listing_rank": 3,
                "listing_payload": {"source_job_id": "ctgoodjobs-published"},
            },
        ],
        skip_existing=True,
    )

    verification_db = session_factory()
    crawl_job_repository = CrawlJobRepository()
    refreshed_listing_job = crawl_job_repository.get_crawl_job_by_id(
        verification_db,
        current_listing_batch_id,
    )
    current_batch_rows = (
        verification_db.query(CrawlJobListing)
        .filter(CrawlJobListing.crawl_job_id == current_listing_batch_id)
        .order_by(CrawlJobListing.listing_rank.asc())
        .all()
    )

    assert [row.source_job_id for row in current_batch_rows] == ["ctgoodjobs-new"]
    assert refreshed_listing_job.metrics["jobs_skipped_existing"] == 2
    assert refreshed_listing_job.metrics["listings_staged"] == 1
    verification_db.close()


def test_listing_resume_keeps_existing_progress_counters_in_started_and_page_events():
    session_factory = _build_session_factory()
    db = session_factory()
    crawl_job = _create_crawl_job(
        db,
        request_payload={
            "crawl_phase": "listing",
            "source_site": "jobsdb",
            "skip_existing": True,
        },
    )
    _create_listing(
        db,
        crawl_job_id=crawl_job.id,
        source_job_id="seen-1",
        detail_status="pending",
        listing_rank=1,
    )
    _create_listing(
        db,
        crawl_job_id=crawl_job.id,
        source_job_id="seen-2",
        detail_status="pending",
        listing_rank=2,
    )
    crawl_job.metrics = {
        "pages_processed": 4,
        "job_ids_collected": 2,
        "jobs_skipped_existing": 3,
        "listings_staged": 2,
    }
    db.commit()
    crawl_job_id = crawl_job.id
    db.close()

    class ResumeRunner:
        async def crawl(self, **kwargs):
            kwargs["emit_listing_emitted"](
                {
                    "source_site": "jobsdb",
                    "source_job_id": "brand-new-after-resume",
                    "source_url": "https://example.test/jobs/brand-new-after-resume",
                    "source_classification_id": "1200",
                    "source_classification_name": "Engineering",
                    "listing_page": 5,
                    "listing_rank": 3,
                    "listing_payload": {"source_job_id": "brand-new-after-resume"},
                }
            )
            kwargs["emit_listing_emitted"](
                {
                    "source_site": "jobsdb",
                    "source_job_id": "existing-after-resume",
                    "source_url": "https://example.test/jobs/existing-after-resume",
                    "source_classification_id": "1200",
                    "source_classification_name": "Engineering",
                    "listing_page": 5,
                    "listing_rank": 4,
                    "listing_payload": {"source_job_id": "existing-after-resume"},
                }
            )
            kwargs["emit_page_processed"]({"current_page": 5, "total_pages": 10})
            return {
                "pages_processed": 5,
                "items_emitted": 0,
            }

    bus = FakeBus()
    worker = CrawlWorkerService(
        bus=bus,
        runner_registry={"jobsdb": ResumeRunner()},
        job_repository=FakeJobRepository(
            existing_by_source_job_id={
                "existing-after-resume": SimpleNamespace(id=uuid4()),
            }
        ),
        session_factory=session_factory,
    )
    event = build_event_envelope(
        event_type="crawl.requested",
        aggregate_type="crawl_job",
        aggregate_id=str(crawl_job_id),
        source_service="test",
        payload={
            "crawl_job_id": str(crawl_job_id),
            "source_site": "jobsdb",
            "request_payload": {
                "source_site": "jobsdb",
                "crawl_phase": "listing",
                "category_ids": [1200],
                "max_pages": 10,
                "skip_existing": True,
                "is_resume": True,
                "resume_context": {
                    "listing_rank": 2,
                    "seen_job_ids": ["seen-1", "seen-2"],
                },
            },
        },
    )

    asyncio.run(worker._handle_message(SimpleNamespace(event=event, message_id="message-resume")))

    started_payload = next(
        envelope.payload
        for topic, envelope in bus.published
        if topic == STREAM_CRAWL_PROGRESS and envelope.event_type == "crawl.started"
    )
    page_payload = next(
        envelope.payload
        for topic, envelope in bus.published
        if topic == STREAM_CRAWL_PROGRESS and envelope.event_type == "crawl.page_processed"
    )

    assert started_payload.get("job_ids_collected") == 2
    assert started_payload.get("jobs_skipped_existing") == 3
    assert started_payload.get("listings_staged") == 2
    assert page_payload["pages_processed"] == 5
    assert page_payload["job_ids_collected"] == 3
    assert page_payload["jobs_skipped_existing"] == 4
    assert page_payload["listings_staged"] == 3

    verification_db = session_factory()
    refreshed_listing_job = CrawlJobRepository().get_crawl_job_by_id(
        verification_db,
        crawl_job_id,
    )

    assert refreshed_listing_job.metrics["pages_processed"] == 5
    assert refreshed_listing_job.metrics["job_ids_collected"] == 3
    assert refreshed_listing_job.metrics["jobs_skipped_existing"] == 4
    assert refreshed_listing_job.metrics["listings_staged"] == 3
    verification_db.close()


def test_ctgoodjobs_worker_started_payload_exposes_proxy_runtime_metadata(monkeypatch):
    bus = FakeBus()

    class FakeRunner:
        async def crawl(self, **_kwargs):
            return {
                "pages_processed": 0,
                "items_emitted": 0,
            }

    worker = CrawlWorkerService(
        bus=bus,
        runner_registry={"ctgoodjobs": FakeRunner()},
        session_factory=_build_session_factory(),
    )
    monkeypatch.setattr(worker, "_persist_runtime_event", lambda **_kwargs: None)

    event = build_event_envelope(
        event_type="crawl.requested",
        aggregate_type="crawl_job",
        aggregate_id="job-1",
        source_service="test",
        payload={
            "crawl_job_id": "job-1",
            "source_site": "ctgoodjobs",
            "request_payload": {
                "source_site": "ctgoodjobs",
                "crawl_phase": "listing",
                "crawl_mode": "headless",
                "category_ids": ["ctgoodjobs:021"],
                "max_pages": 1,
            },
        },
    )

    asyncio.run(worker._handle_message(SimpleNamespace(event=event, message_id="message-1")))

    started_envelopes = [
        envelope
        for topic, envelope in bus.published
        if topic == STREAM_CRAWL_PROGRESS and envelope.event_type == "crawl.started"
    ]
    assert len(started_envelopes) == 1

    started_payload = started_envelopes[0].payload
    assert started_payload["proxy_enabled"] is False
    assert started_payload["proxy_provider"] == "disabled"
    assert started_payload["proxy_requests_total"] == 0
    assert started_payload["proxy_requests_success"] == 0
    assert started_payload["proxy_requests_challenge"] == 0
    assert started_payload["proxy_requests_network_fail"] == 0
    assert started_payload["proxy_requests_http_fail"] == 0
    assert started_payload["proxy_quarantined_total"] == 0
    assert started_payload["proxy_metrics_by_stage"]["registry"]["proxy_requests_total"] == 0
    assert started_payload["proxy_metrics_by_stage"]["category_page"]["proxy_requests_total"] == 0
    assert started_payload["proxy_metrics_by_stage"]["detail_page"]["proxy_requests_total"] == 0


def test_ctgoodjobs_manual_action_progress_preserves_proxy_unavailable_stage(monkeypatch):
    bus = FakeBus()

    class FailingRunner:
        async def crawl(self, **_kwargs):
            raise ManualActionRequiredError(
                source_site="ctgoodjobs",
                stage="proxy_unavailable",
                blocked_url="https://jobs.ctgoodjobs.hk/jobs",
                message="No usable CTGoodJobs proxy lease is available. Check the proxy configuration or try again later.",
                instructions=[
                    "Verify the CTGoodJobs proxy settings and provider availability.",
                    "Return to the app and click Resume after proxy availability is restored.",
                ],
            )

    worker = CrawlWorkerService(
        bus=bus,
        runner_registry={"ctgoodjobs": FailingRunner()},
        session_factory=_build_session_factory(),
    )
    monkeypatch.setattr(worker, "_persist_runtime_event", lambda **_kwargs: None)

    event = build_event_envelope(
        event_type="crawl.requested",
        aggregate_type="crawl_job",
        aggregate_id="job-proxy-unavailable",
        source_service="test",
        payload={
            "crawl_job_id": "job-proxy-unavailable",
            "source_site": "ctgoodjobs",
            "request_payload": {
                "source_site": "ctgoodjobs",
                "crawl_phase": "listing",
                "crawl_mode": "headed",
                "category_ids": ["ctgoodjobs:021"],
                "max_pages": 1,
            },
        },
    )

    asyncio.run(worker._handle_message(SimpleNamespace(event=event, message_id="message-proxy-unavailable")))

    action_required_envelopes = [
        envelope
        for topic, envelope in bus.published
        if topic == STREAM_CRAWL_PROGRESS and envelope.event_type == "crawl.manual_action_required"
    ]
    assert len(action_required_envelopes) == 1

    payload = action_required_envelopes[0].payload
    assert payload["error"] == "No usable CTGoodJobs proxy lease is available. Check the proxy configuration or try again later."
    assert payload["manual_action"]["stage"] == "proxy_unavailable"
    assert payload["manual_action"]["message"] == payload["error"]
    assert payload["manual_action"]["instructions"] == [
        "Verify the CTGoodJobs proxy settings and provider availability.",
        "Return to the app and click Resume after proxy availability is restored.",
    ]
