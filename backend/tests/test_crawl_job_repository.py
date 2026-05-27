from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.crawl_job import CrawlJob, CrawlJobEvent
from app.repositories.crawl_job_repository import CrawlJobRepository


def _build_session_factory():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CrawlJob.__table__,
            CrawlJobEvent.__table__,
        ],
    )
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_get_latest_manual_action_event_returns_latest_matching_event():
    session_factory = _build_session_factory()
    db = session_factory()
    repository = CrawlJobRepository()

    crawl_job = CrawlJob(
        source_site="ctgoodjobs",
        trigger_type="manual",
        status="running",
        request_payload={"crawl_phase": "detail", "source_site": "ctgoodjobs"},
        queued_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
    )
    db.add(crawl_job)
    db.commit()
    db.refresh(crawl_job)

    db.add_all(
        [
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=1,
                event_type="crawl.started",
                payload={"status": "running"},
                created_at=datetime(2026, 5, 27, 9, 1, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=2,
                event_type="crawl.manual_action_required",
                payload={"manual_action": {"stage": "browser_profile_in_use"}},
                created_at=datetime(2026, 5, 27, 9, 2, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=3,
                event_type="crawl.page_processed",
                payload={"current_page": 2},
                created_at=datetime(2026, 5, 27, 9, 3, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=4,
                event_type="crawl.manual_action_required",
                payload={"manual_action": {"stage": "proxy_unavailable"}},
                created_at=datetime(2026, 5, 27, 9, 4, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    event = repository.get_latest_manual_action_event(db, crawl_job.id)

    assert event is not None
    assert event.sequence_no == 4
    assert event.event_type == "crawl.manual_action_required"
    assert event.payload["manual_action"]["stage"] == "proxy_unavailable"

    db.close()


def test_list_events_can_filter_by_event_type_while_preserving_sequence_order():
    session_factory = _build_session_factory()
    db = session_factory()
    repository = CrawlJobRepository()

    crawl_job = CrawlJob(
        source_site="ctgoodjobs",
        trigger_type="manual",
        status="running",
        request_payload={"crawl_phase": "detail", "source_site": "ctgoodjobs"},
        queued_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
    )
    db.add(crawl_job)
    db.commit()
    db.refresh(crawl_job)

    db.add_all(
        [
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=1,
                event_type="crawl.started",
                payload={"status": "running"},
                created_at=datetime(2026, 5, 27, 9, 1, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=2,
                event_type="crawl.page_processed",
                payload={"current_page": 1},
                created_at=datetime(2026, 5, 27, 9, 2, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=3,
                event_type="crawl.manual_action_required",
                payload={"manual_action": {"stage": "browser_profile_in_use"}},
                created_at=datetime(2026, 5, 27, 9, 3, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    events = repository.list_events(
        db,
        crawl_job.id,
        event_types={"crawl.started", "crawl.manual_action_required"},
    )

    assert [event.sequence_no for event in events] == [1, 3]
    assert [event.event_type for event in events] == [
        "crawl.started",
        "crawl.manual_action_required",
    ]

    db.close()
