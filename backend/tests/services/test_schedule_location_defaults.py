from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from app.models.schedule import ScrapeSchedule
from app.schemas.schedule import ScheduleCreateSchema, ScheduleSchema
from app.services.crawl_job_dispatch_service import CrawlJobDispatchService


def test_schedule_create_schema_does_not_default_location():
    schedule = ScheduleCreateSchema(
        name="Nightly scrape",
        cron_expression="0 2 * * *",
    )

    assert schedule.location is None


def test_schedule_schema_allows_null_location():
    now = datetime.utcnow()

    schedule = ScheduleSchema.model_validate(
        {
            "id": uuid4(),
            "name": "Nightly scrape",
            "description": None,
            "cron_expression": "0 2 * * *",
            "timezone": "Asia/Hong_Kong",
            "source_site": "jobsdb",
            "crawl_phase": "listing",
            "crawl_mode": "headed",
            "category_ids": None,
            "keywords": None,
            "location": None,
            "max_pages": 3,
            "detail_limit": 100,
            "is_active": True,
            "last_run_at": None,
            "next_run_at": None,
            "created_at": now,
            "updated_at": now,
        }
    )

    assert schedule.location is None


def test_schedule_model_location_has_no_orm_default():
    assert ScrapeSchedule.__table__.c.location.default is None


def test_build_schedule_request_payload_omits_empty_location():
    schedule = SimpleNamespace(
        source_site="jobsdb",
        crawl_phase="listing",
        crawl_mode=None,
        category_ids=[],
        keywords=None,
        location=None,
        max_pages=3,
        detail_limit=100,
    )

    payload = CrawlJobDispatchService().build_schedule_request_payload(
        schedule=schedule
    )

    assert "location" not in payload


def test_build_schedule_request_payload_preserves_non_empty_location():
    schedule = SimpleNamespace(
        source_site="jobsdb",
        crawl_phase="listing",
        crawl_mode=None,
        category_ids=[],
        keywords=None,
        location="Hong Kong Island",
        max_pages=3,
        detail_limit=100,
    )

    payload = CrawlJobDispatchService().build_schedule_request_payload(
        schedule=schedule
    )

    assert payload["location"] == "Hong Kong Island"
