import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.scraper_pacing_settings import ScraperPacingSettings
from app.repositories.crawl_job_repository import CrawlJobRepository
from app.schemas.scraper_pacing import DetailPacingConfig
from app.services.scraper_pacing_settings_service import (
    DEFAULT_DETAIL_PACING,
    ScraperPacingSettingsService,
)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    ScraperPacingSettings.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_defaults_create_exactly_three_independent_sources(db):
    service = ScraperPacingSettingsService(db)
    rows = service.list_settings()

    assert [row.source_site for row in rows] == [
        "jobsdb",
        "ctgoodjobs",
        "offertoday",
    ]
    assert all(
        row.interval_min_seconds == DEFAULT_DETAIL_PACING.interval_min_seconds
        and row.interval_max_seconds == DEFAULT_DETAIL_PACING.interval_max_seconds
        and row.burst_size == DEFAULT_DETAIL_PACING.burst_size
        and row.burst_pause_seconds == DEFAULT_DETAIL_PACING.burst_pause_seconds
        for row in rows
    )

    service.update(
        "ctgoodjobs",
        {
            "interval_min_seconds": 2,
            "interval_max_seconds": 4,
            "burst_size": 10,
            "burst_pause_seconds": 15,
        },
    )
    assert service.resolve("ctgoodjobs").interval_min_seconds == 2
    assert service.resolve("jobsdb").interval_min_seconds == 1
    assert service.resolve("offertoday").interval_min_seconds == 1

    reset = service.reset("ctgoodjobs")
    assert reset.interval_min_seconds == 1
    assert reset.interval_max_seconds == 3
    assert reset.burst_size == 20
    assert reset.burst_pause_seconds == 30


@pytest.mark.parametrize(
    "payload",
    [
        dict(interval_min_seconds=0, interval_max_seconds=1, burst_size=20, burst_pause_seconds=30),
        dict(interval_min_seconds=1, interval_max_seconds=61, burst_size=20, burst_pause_seconds=30),
        dict(interval_min_seconds=3, interval_max_seconds=1, burst_size=20, burst_pause_seconds=30),
        dict(interval_min_seconds=1, interval_max_seconds=3, burst_size=0, burst_pause_seconds=30),
        dict(interval_min_seconds=1, interval_max_seconds=3, burst_size=1001, burst_pause_seconds=30),
        dict(interval_min_seconds=1, interval_max_seconds=3, burst_size=20, burst_pause_seconds=3601),
    ],
)
def test_schema_rejects_values_outside_safety_boundaries(payload):
    with pytest.raises(ValidationError):
        DetailPacingConfig.model_validate(payload)


def test_schema_accepts_exact_safety_boundaries():
    assert DetailPacingConfig(
        interval_min_seconds=0.1,
        interval_max_seconds=60,
        burst_size=1,
        burst_pause_seconds=0,
    )
    assert DetailPacingConfig(
        interval_min_seconds=60,
        interval_max_seconds=60,
        burst_size=1000,
        burst_pause_seconds=3600,
    )


def test_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        DetailPacingConfig(
            interval_min_seconds=1,
            interval_max_seconds=3,
            burst_size=20,
            burst_pause_seconds=30,
            unexpected=True,
        )


def test_active_manual_detail_count_ignores_listing_payloads():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [
        SimpleNamespace(request_payload={"crawl_phase": "detail"}),
        SimpleNamespace(request_payload={"crawl_phase": "listing"}),
        SimpleNamespace(request_payload={"crawl_phase": "DETAIL"}),
        SimpleNamespace(request_payload={}),
    ]

    count = CrawlJobRepository().count_active_manual_detail_jobs(
        db,
        statuses=frozenset({"running", "cancelling"}),
    )

    assert count == 2
