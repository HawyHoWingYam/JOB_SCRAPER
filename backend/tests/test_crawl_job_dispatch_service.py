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
from app.messaging.outbox_publisher import OutboxPublisher
from app.messaging.topics import STREAM_CRAWL_COMMANDS, STREAM_CRAWL_COMMANDS_HEADED
from app.models import CrawlJob, CrawlJobEvent, EventOutbox, ScrapeSchedule, ScheduleExecution
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService


if not hasattr(SQLiteTypeCompiler, "visit_UUID"):
    SQLiteTypeCompiler.visit_UUID = lambda self, type_, **kw: "CHAR(32)"

if not hasattr(SQLiteTypeCompiler, "visit_ARRAY"):
    SQLiteTypeCompiler.visit_ARRAY = lambda self, type_, **kw: "TEXT"


class RecordingBus:
    def __init__(self):
        self.published = []

    def publish(self, topic, envelope):
        self.published.append((topic, envelope))


def _build_session():
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


def _create_schedule(db, *, source_site="jobsdb", category_ids=None):
    schedule = ScrapeSchedule(
        id=uuid.uuid4(),
        name=f"{source_site} nightly",
        cron_expression="0 2 * * *",
        timezone="Asia/Hong_Kong",
        source_site=source_site,
        crawl_phase="listing",
        detail_limit=100,
        category_ids=category_ids if category_ids is not None else [1200],
        max_pages=3,
        is_active=True,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    return schedule


def test_dispatch_manual_crawl_job_publishes_crawl_requested_event():
    db = _build_session()
    bus = RecordingBus()
    service = CrawlJobDispatchService(
        outbox_publisher=OutboxPublisher(stream_bus=bus),
    )

    try:
        result = service.dispatch_manual_crawl_job(
            db,
            source_site="jobsdb",
            category_ids=[1200],
            max_pages=3,
            requested_by="api",
        )

        outbox_rows = db.query(EventOutbox).order_by(EventOutbox.id.asc()).all()

        assert result.crawl_job.status == "queued"
        assert len(outbox_rows) == 1
        assert outbox_rows[0].status == "published"
        assert outbox_rows[0].published_at is not None
        assert result.crawl_job.request_payload["crawl_phase"] == "listing"
        assert len(bus.published) == 1
        assert bus.published[0][0] == STREAM_CRAWL_COMMANDS_HEADED
        assert bus.published[0][1].event_type == "crawl.requested"
    finally:
        db.close()


def test_dispatch_manual_crawl_job_can_force_headless_topic():
    db = _build_session()
    bus = RecordingBus()
    service = CrawlJobDispatchService(
        outbox_publisher=OutboxPublisher(stream_bus=bus),
    )

    try:
        result = service.dispatch_manual_crawl_job(
            db,
            source_site="jobsdb",
            category_ids=[1200],
            max_pages=3,
            crawl_mode="headless",
            requested_by="api",
        )

        outbox_rows = db.query(EventOutbox).order_by(EventOutbox.id.asc()).all()

        assert result.crawl_job.request_payload["crawl_mode"] == "headless"
        assert result.crawl_job.request_payload["crawl_phase"] == "listing"
        assert outbox_rows[0].topic == STREAM_CRAWL_COMMANDS
        assert bus.published[0][0] == STREAM_CRAWL_COMMANDS
    finally:
        db.close()


def test_dispatch_manual_detail_crawl_job_publishes_target_batch_and_limit():
    db = _build_session()
    bus = RecordingBus()
    service = CrawlJobDispatchService(
        outbox_publisher=OutboxPublisher(stream_bus=bus),
    )

    try:
        source_listing_crawl_job_id = uuid.uuid4()
        result = service.dispatch_manual_crawl_job(
            db,
            source_site="jobsdb",
            category_ids=[],
            max_pages=3,
            crawl_phase="detail",
            source_listing_crawl_job_id=source_listing_crawl_job_id,
            detail_limit=25,
            requested_by="api",
        )

        assert result.crawl_job.request_payload["crawl_phase"] == "detail"
        assert result.crawl_job.request_payload["source_listing_crawl_job_id"] == str(source_listing_crawl_job_id)
        assert result.crawl_job.request_payload["detail_limit"] == 25
        assert bus.published[0][0] == STREAM_CRAWL_COMMANDS_HEADED
    finally:
        db.close()


def test_dispatch_schedule_crawl_job_publishes_crawl_requested_event():
    db = _build_session()
    bus = RecordingBus()
    service = CrawlJobDispatchService(
        outbox_publisher=OutboxPublisher(stream_bus=bus),
    )

    try:
        schedule = _create_schedule(db, source_site="ctgoodjobs", category_ids=["ctgoodjobs:021"])
        result = service.dispatch_schedule_crawl_job(
            db,
            schedule=schedule,
            requested_by="scheduler-worker",
            trigger_type="schedule",
        )

        outbox_rows = db.query(EventOutbox).order_by(EventOutbox.id.asc()).all()
        execution = db.query(ScheduleExecution).filter(ScheduleExecution.schedule_id == schedule.id).one()

        assert result.crawl_job.id == execution.crawl_job_id
        assert len(outbox_rows) == 1
        assert outbox_rows[0].status == "published"
        assert outbox_rows[0].topic == STREAM_CRAWL_COMMANDS_HEADED
        assert result.crawl_job.request_payload["crawl_mode"] == "headed"
        assert result.crawl_job.request_payload["crawl_phase"] == "listing"
        assert len(bus.published) == 1
        assert bus.published[0][1].event_type == "crawl.requested"
    finally:
        db.close()


def test_dispatch_schedule_detail_crawl_job_uses_schedule_phase_and_detail_limit():
    db = _build_session()
    bus = RecordingBus()
    service = CrawlJobDispatchService(
        outbox_publisher=OutboxPublisher(stream_bus=bus),
    )

    try:
        schedule = _create_schedule(db, source_site="jobsdb", category_ids=[6281])
        schedule.crawl_phase = "detail"
        schedule.detail_limit = 40
        db.commit()
        db.refresh(schedule)

        result = service.dispatch_schedule_crawl_job(
            db,
            schedule=schedule,
            requested_by="scheduler-worker",
            trigger_type="schedule",
        )

        assert result.crawl_job.request_payload["crawl_phase"] == "detail"
        assert result.crawl_job.request_payload["detail_limit"] == 40
        assert result.crawl_job.request_payload["category_ids"] == [6281]
    finally:
        db.close()


def test_cancel_crawl_job_publishes_crawl_cancelled_event():
    db = _build_session()
    bus = RecordingBus()
    service = CrawlJobDispatchService(
        outbox_publisher=OutboxPublisher(stream_bus=bus),
    )

    try:
        created = service.dispatch_manual_crawl_job(
            db,
            source_site="jobsdb",
            category_ids=[1200],
            max_pages=3,
            requested_by="api",
        )

        bus.published.clear()
        cancelled = service.cancel_crawl_job(
            db,
            crawl_job_id=created.crawl_job.id,
            requested_by="api",
        )
        outbox_rows = db.query(EventOutbox).order_by(EventOutbox.id.asc()).all()

        assert cancelled.status == "cancelled"
        assert outbox_rows[-1].status == "published"
        assert len(bus.published) == 1
        assert bus.published[0][1].event_type == "crawl.cancelled"
    finally:
        db.close()
