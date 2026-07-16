from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.scraper_pacing_settings import ScraperPacingSettings
from app.services.crawl_job_dispatch_service import (
    ACTIVE_MANUAL_DETAIL_STATUSES,
    ActiveManualDetailCrawlConflict,
    CrawlJobDispatchService,
)


class _Repository:
    def __init__(self, conflicts=None):
        self.conflicts = list(conflicts or [])
        self.queries = []

    def list_active_manual_detail_jobs_for_update(self, _db, **kwargs):
        self.queries.append(kwargs)
        return self.conflicts


class _CapturingDispatchService(CrawlJobDispatchService):
    def dispatch_crawl_job(self, _db, **kwargs):
        return SimpleNamespace(
            crawl_job=SimpleNamespace(request_payload=kwargs["request_payload"]),
            schedule_execution=None,
        )


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    ScraperPacingSettings.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        ScraperPacingSettings(
            source_site="jobsdb",
            interval_min_seconds=1,
            interval_max_seconds=3,
            burst_size=20,
            burst_pause_seconds=30,
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _dispatch(service, db, *, phase="detail"):
    return service.dispatch_manual_crawl_job(
        db,
        source_site="jobsdb",
        crawl_phase=phase,
        category_ids=[],
        max_pages=1,
    )


def test_manual_detail_dispatch_snapshots_effective_settings(db):
    repository = _Repository()
    service = _CapturingDispatchService(crawl_job_repository=repository)

    result = _dispatch(service, db)
    snapshot = result.crawl_job.request_payload["detail_pacing"]

    assert snapshot == {
        "interval_min_seconds": 1.0,
        "interval_max_seconds": 3.0,
        "burst_size": 20,
        "burst_pause_seconds": 30.0,
    }
    assert repository.queries == [
        {"source_site": "jobsdb", "statuses": ACTIVE_MANUAL_DETAIL_STATUSES}
    ]

    db.query(ScraperPacingSettings).filter_by(source_site="jobsdb").update(
        {"interval_min_seconds": 5, "interval_max_seconds": 7}
    )
    db.commit()
    assert result.crawl_job.request_payload["detail_pacing"] == snapshot


def test_manual_detail_dispatch_rejects_same_source_active_task(db):
    repository = _Repository(conflicts=[SimpleNamespace(id="active-task")])
    service = _CapturingDispatchService(crawl_job_repository=repository)

    with pytest.raises(ActiveManualDetailCrawlConflict, match="active-task"):
        _dispatch(service, db)


def test_listing_dispatch_does_not_snapshot_or_query_detail_conflicts(db):
    repository = _Repository()
    service = _CapturingDispatchService(crawl_job_repository=repository)

    result = _dispatch(service, db, phase="listing")

    assert "detail_pacing" not in result.crawl_job.request_payload
    assert repository.queries == []
