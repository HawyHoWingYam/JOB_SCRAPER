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


def test_list_latest_events_for_jobs_returns_latest_event_per_job():
    session_factory = _build_session_factory()
    db = session_factory()
    repository = CrawlJobRepository()

    first_job = CrawlJob(
        source_site="jobsdb",
        trigger_type="manual",
        status="running",
        request_payload={"crawl_phase": "listing", "source_site": "jobsdb"},
        queued_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
    )
    second_job = CrawlJob(
        source_site="ctgoodjobs",
        trigger_type="manual",
        status="running",
        request_payload={"crawl_phase": "detail", "source_site": "ctgoodjobs"},
        queued_at=datetime(2026, 5, 27, 9, 5, tzinfo=UTC),
    )
    db.add_all([first_job, second_job])
    db.commit()
    db.refresh(first_job)
    db.refresh(second_job)

    db.add_all(
        [
            CrawlJobEvent(
                crawl_job_id=first_job.id,
                sequence_no=1,
                event_type="crawl.started",
                payload={"phase": 1},
                created_at=datetime(2026, 5, 27, 9, 1, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=first_job.id,
                sequence_no=2,
                event_type="crawl.page_processed",
                payload={"current_page": 1},
                created_at=datetime(2026, 5, 27, 9, 2, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=second_job.id,
                sequence_no=1,
                event_type="crawl.started",
                payload={"phase": 2},
                created_at=datetime(2026, 5, 27, 9, 6, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=second_job.id,
                sequence_no=2,
                event_type="crawl.manual_action_required",
                payload={"manual_action": {"stage": "proxy_unavailable"}},
                created_at=datetime(2026, 5, 27, 9, 7, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    latest_events = repository.list_latest_events_for_jobs(
        db,
        crawl_job_ids=[first_job.id, second_job.id],
    )

    assert latest_events[first_job.id].sequence_no == 2
    assert latest_events[first_job.id].event_type == "crawl.page_processed"
    assert latest_events[second_job.id].sequence_no == 2
    assert latest_events[second_job.id].event_type == "crawl.manual_action_required"

    db.close()


def test_list_events_by_job_ids_can_filter_by_event_type_while_preserving_sequence_order():
    session_factory = _build_session_factory()
    db = session_factory()
    repository = CrawlJobRepository()

    first_job = CrawlJob(
        source_site="jobsdb",
        trigger_type="manual",
        status="running",
        request_payload={"crawl_phase": "listing", "source_site": "jobsdb"},
        queued_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
    )
    second_job = CrawlJob(
        source_site="ctgoodjobs",
        trigger_type="manual",
        status="running",
        request_payload={"crawl_phase": "detail", "source_site": "ctgoodjobs"},
        queued_at=datetime(2026, 5, 27, 9, 5, tzinfo=UTC),
    )
    db.add_all([first_job, second_job])
    db.commit()
    db.refresh(first_job)
    db.refresh(second_job)

    db.add_all(
        [
            CrawlJobEvent(
                crawl_job_id=first_job.id,
                sequence_no=1,
                event_type="crawl.started",
                payload={"phase": 1},
                created_at=datetime(2026, 5, 27, 9, 1, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=first_job.id,
                sequence_no=2,
                event_type="crawl.page_processed",
                payload={"current_page": 1},
                created_at=datetime(2026, 5, 27, 9, 2, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=second_job.id,
                sequence_no=1,
                event_type="crawl.started",
                payload={"phase": 2},
                created_at=datetime(2026, 5, 27, 9, 6, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=second_job.id,
                sequence_no=2,
                event_type="crawl.manual_action_required",
                payload={"manual_action": {"stage": "proxy_unavailable"}},
                created_at=datetime(2026, 5, 27, 9, 7, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    grouped_events = repository.list_events_by_job_ids(
        db,
        crawl_job_ids=[first_job.id, second_job.id],
        event_types={"crawl.started", "crawl.manual_action_required"},
    )

    assert [event.sequence_no for event in grouped_events[first_job.id]] == [1]
    assert [event.event_type for event in grouped_events[first_job.id]] == ["crawl.started"]
    assert [event.sequence_no for event in grouped_events[second_job.id]] == [1, 2]
    assert [event.event_type for event in grouped_events[second_job.id]] == [
        "crawl.started",
        "crawl.manual_action_required",
    ]

    db.close()


def test_list_events_can_return_latest_tail_while_preserving_sequence_order():
    session_factory = _build_session_factory()
    db = session_factory()
    repository = CrawlJobRepository()

    crawl_job = CrawlJob(
        source_site="jobsdb",
        trigger_type="manual",
        status="running",
        request_payload={"crawl_phase": "listing", "source_site": "jobsdb"},
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
                event_type="crawl.requested",
                payload={"current_page": 0},
                created_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=2,
                event_type="crawl.started",
                payload={"current_page": 0},
                created_at=datetime(2026, 5, 27, 9, 1, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=3,
                event_type="crawl.page_processed",
                payload={"current_page": 1},
                created_at=datetime(2026, 5, 27, 9, 2, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=4,
                event_type="crawl.page_processed",
                payload={"current_page": 2},
                created_at=datetime(2026, 5, 27, 9, 3, tzinfo=UTC),
            ),
            CrawlJobEvent(
                crawl_job_id=crawl_job.id,
                sequence_no=5,
                event_type="crawl.completed",
                payload={"current_page": 2},
                created_at=datetime(2026, 5, 27, 9, 4, tzinfo=UTC),
            ),
        ]
    )
    db.commit()

    events = repository.list_events(
        db,
        crawl_job.id,
        limit=2,
        tail=True,
    )

    assert [event.sequence_no for event in events] == [4, 5]
    assert [event.event_type for event in events] == [
        "crawl.page_processed",
        "crawl.completed",
    ]

    db.close()
