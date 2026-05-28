from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.crawl_job import CrawlJob
from app.models.schedule import ScheduleExecution, ScrapeSchedule
from app.repositories.schedule_repository import ScheduleRepository


def test_get_all_schedules_attaches_latest_execution_summary():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            ScheduleExecution.__table__,
            CrawlJob.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    repository = ScheduleRepository()

    schedule = ScrapeSchedule(
        id=uuid4(),
        name="JobsDB Nightly",
        cron_expression="0 2 * * *",
        source_site="jobsdb",
        crawl_phase="listing",
        crawl_mode="headed",
        category_ids=[1200],
        is_active=True,
        created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
    )
    db.add(schedule)
    db.commit()
    older_crawl_job_id = uuid4()
    latest_crawl_job_id = uuid4()

    db.add_all(
        [
            ScheduleExecution(
                id=uuid4(),
                schedule_id=schedule.id,
                crawl_job_id=older_crawl_job_id,
                status="failed",
                started_at=datetime(2026, 5, 27, 8, 0, tzinfo=UTC),
                completed_at=datetime(2026, 5, 27, 8, 5, tzinfo=UTC),
                duration_seconds=300,
                jobs_scraped=10,
                jobs_saved=8,
            ),
            ScheduleExecution(
                id=uuid4(),
                schedule_id=schedule.id,
                crawl_job_id=latest_crawl_job_id,
                status="completed_with_ai_failures",
                started_at=datetime(2026, 5, 28, 8, 0, tzinfo=UTC),
                completed_at=datetime(2026, 5, 28, 8, 5, tzinfo=UTC),
                duration_seconds=300,
                jobs_scraped=12,
                jobs_saved=11,
            ),
        ]
    )
    db.add_all(
        [
            CrawlJob(
                id=older_crawl_job_id,
                source_site="jobsdb",
                trigger_type="manual",
                status="failed",
                request_payload={"crawl_phase": "listing", "source_site": "jobsdb"},
                queued_at=datetime(2026, 5, 27, 7, 55, tzinfo=UTC),
                metrics={"ingest_items_settled": 8},
            ),
            CrawlJob(
                id=latest_crawl_job_id,
                source_site="jobsdb",
                trigger_type="manual",
                status="completed",
                request_payload={"crawl_phase": "listing", "source_site": "jobsdb"},
                queued_at=datetime(2026, 5, 28, 7, 55, tzinfo=UTC),
                metrics={
                    "ingest_items_settled": 12,
                    "ingest_dead_lettered": 1,
                },
            ),
        ]
    )
    db.commit()

    schedules = repository.get_all_schedules(db)

    assert len(schedules) == 1
    enriched_schedule = schedules[0]
    assert enriched_schedule.latest_execution_status == "completed_with_ai_failures"
    assert enriched_schedule.latest_execution_jobs_scraped == 12
    assert enriched_schedule.latest_execution_jobs_saved == 11
    assert enriched_schedule.latest_execution_jobs_settled == 12
    assert enriched_schedule.latest_execution_jobs_dead_lettered == 1
    assert enriched_schedule.latest_execution_listings_staged == 0
    assert enriched_schedule.last_run_at == datetime(2026, 5, 28, 8, 0)
    assert enriched_schedule.latest_execution_started_at == datetime(2026, 5, 28, 8, 0)
    assert enriched_schedule.latest_execution_completed_at == datetime(2026, 5, 28, 8, 5)
    db.close()


def test_get_executions_attaches_dead_letter_and_settled_counts_from_linked_crawl_job():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            ScheduleExecution.__table__,
            CrawlJob.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    repository = ScheduleRepository()

    schedule = ScrapeSchedule(
        id=uuid4(),
        name="CTGoodJobs Detail Recovery",
        cron_expression="0 2 * * *",
        source_site="ctgoodjobs",
        crawl_phase="detail",
        crawl_mode="headed",
        category_ids=["ctgoodjobs:021"],
        is_active=True,
        created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
    )
    crawl_job_id = uuid4()
    db.add(schedule)
    db.add(
        CrawlJob(
            id=crawl_job_id,
            source_site="ctgoodjobs",
            trigger_type="manual",
            status="completed",
            request_payload={"crawl_phase": "detail", "source_site": "ctgoodjobs"},
            queued_at=datetime(2026, 5, 28, 7, 55, tzinfo=UTC),
            metrics={
                "ingest_items_settled": 100,
                "ingest_dead_lettered": 70,
            },
        )
    )
    db.add(
        ScheduleExecution(
            id=uuid4(),
            schedule_id=schedule.id,
            crawl_job_id=crawl_job_id,
            status="completed",
            started_at=datetime(2026, 5, 28, 8, 0, tzinfo=UTC),
            completed_at=datetime(2026, 5, 28, 8, 5, tzinfo=UTC),
            duration_seconds=300,
            jobs_scraped=100,
            jobs_saved=30,
        )
    )
    db.commit()

    executions = repository.get_executions(db, schedule.id, limit=20)

    assert len(executions) == 1
    assert executions[0].jobs_saved == 30
    assert executions[0].jobs_settled == 100
    assert executions[0].jobs_dead_lettered == 70
    db.close()


def test_get_all_schedules_attaches_backlog_summary_for_listing_runs():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            ScheduleExecution.__table__,
            CrawlJob.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    repository = ScheduleRepository()

    schedule = ScrapeSchedule(
        id=uuid4(),
        name="JobsDB ICT E2E",
        cron_expression="0 2 * * *",
        source_site="jobsdb",
        crawl_phase="listing",
        crawl_mode="headed",
        category_ids=[6281],
        is_active=True,
        created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
    )
    crawl_job_id = uuid4()
    db.add(schedule)
    db.add(
        CrawlJob(
            id=crawl_job_id,
            source_site="jobsdb",
            trigger_type="manual",
            status="completed",
            request_payload={"crawl_phase": "listing", "source_site": "jobsdb"},
            queued_at=datetime(2026, 5, 28, 7, 55, tzinfo=UTC),
            metrics={
                "listings_staged": 96,
                "detail_pending": 89,
                "detail_completed": 7,
            },
        )
    )
    db.add(
        ScheduleExecution(
            id=uuid4(),
            schedule_id=schedule.id,
            crawl_job_id=crawl_job_id,
            status="completed",
            started_at=datetime(2026, 5, 28, 8, 0, tzinfo=UTC),
            completed_at=datetime(2026, 5, 28, 8, 5, tzinfo=UTC),
            duration_seconds=300,
            jobs_scraped=0,
            jobs_saved=0,
        )
    )
    db.commit()

    schedules = repository.get_all_schedules(db)

    assert len(schedules) == 1
    enriched_schedule = schedules[0]
    assert enriched_schedule.latest_execution_jobs_scraped == 0
    assert enriched_schedule.latest_execution_jobs_saved == 0
    assert enriched_schedule.latest_execution_listings_staged == 96
    assert enriched_schedule.latest_execution_detail_pending == 89
    assert enriched_schedule.latest_execution_detail_completed == 7
    db.close()


def test_get_all_schedules_attaches_running_detail_counts_for_listing_backlog():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            ScheduleExecution.__table__,
            CrawlJob.__table__,
        ],
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    repository = ScheduleRepository()

    schedule = ScrapeSchedule(
        id=uuid4(),
        name="JobsDB Recovery In Flight",
        cron_expression="0 2 * * *",
        source_site="jobsdb",
        crawl_phase="listing",
        crawl_mode="headed",
        category_ids=[6281],
        is_active=True,
        created_at=datetime(2026, 5, 28, 9, 0, tzinfo=UTC),
    )
    crawl_job_id = uuid4()
    db.add(schedule)
    db.add(
        CrawlJob(
            id=crawl_job_id,
            source_site="jobsdb",
            trigger_type="manual",
            status="running",
            request_payload={"crawl_phase": "listing", "source_site": "jobsdb"},
            queued_at=datetime(2026, 5, 28, 7, 55, tzinfo=UTC),
            metrics={
                "listings_staged": 96,
                "detail_pending": 51,
                "detail_running": 12,
                "detail_completed": 22,
            },
        )
    )
    db.add(
        ScheduleExecution(
            id=uuid4(),
            schedule_id=schedule.id,
            crawl_job_id=crawl_job_id,
            status="running",
            started_at=datetime(2026, 5, 28, 8, 0, tzinfo=UTC),
            completed_at=None,
            duration_seconds=None,
            jobs_scraped=0,
            jobs_saved=0,
        )
    )
    db.commit()

    schedules = repository.get_all_schedules(db)

    assert len(schedules) == 1
    enriched_schedule = schedules[0]
    assert enriched_schedule.latest_execution_listings_staged == 96
    assert enriched_schedule.latest_execution_detail_pending == 51
    assert enriched_schedule.latest_execution_detail_running == 12
    assert enriched_schedule.latest_execution_detail_completed == 22
    db.close()
