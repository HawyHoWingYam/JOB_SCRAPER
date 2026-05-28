from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.schedule import ScheduleExecution, ScrapeSchedule
from app.repositories.schedule_repository import ScheduleRepository


def test_get_all_schedules_attaches_latest_execution_summary():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            ScrapeSchedule.__table__,
            ScheduleExecution.__table__,
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

    db.add_all(
        [
            ScheduleExecution(
                id=uuid4(),
                schedule_id=schedule.id,
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
                status="completed_with_ai_failures",
                started_at=datetime(2026, 5, 28, 8, 0, tzinfo=UTC),
                completed_at=datetime(2026, 5, 28, 8, 5, tzinfo=UTC),
                duration_seconds=300,
                jobs_scraped=12,
                jobs_saved=11,
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
    assert enriched_schedule.latest_execution_started_at == datetime(2026, 5, 28, 8, 0)
    assert enriched_schedule.latest_execution_completed_at == datetime(2026, 5, 28, 8, 5)
    db.close()
