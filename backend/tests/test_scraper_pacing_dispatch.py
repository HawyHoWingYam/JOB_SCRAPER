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
    def __init__(self, *, crawl_job_repository):
        self.plan_service = _PlanService()
        super().__init__(
            crawl_job_repository=crawl_job_repository,
            dispatch_plan_service_factory=lambda _db: self.plan_service,
        )

    def dispatch_prepared_plan(self, _db, **kwargs):
        return SimpleNamespace(
            crawl_job=SimpleNamespace(plan_request=self.plan_service.requests[-1]),
            schedule_execution=None,
        )


class _PlanService:
    def __init__(self):
        self.requests = []

    def prepare_run(self, request, **_kwargs):
        self.requests.append(request)
        return SimpleNamespace(
            plan=SimpleNamespace(
                plan_id="plan-id",
                plan_fingerprint="a" * 64,
            ),
            confirmation_token="confirmation-token-value",
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


def test_manual_detail_dispatch_locks_pacing_and_builds_current_plan(db):
    repository = _Repository()
    service = _CapturingDispatchService(crawl_job_repository=repository)

    result = _dispatch(service, db)
    detail_settings = result.crawl_job.plan_request.detail_settings
    assert detail_settings is not None
    assert detail_settings.crawl_mode == "headed"
    assert detail_settings.backlog_scope.kind == "source_backlog"
    assert detail_settings.limit.detail_run_cap == 100
    assert repository.queries == [
        {"source_site": "jobsdb", "statuses": ACTIVE_MANUAL_DETAIL_STATUSES}
    ]

def test_manual_detail_dispatch_rejects_same_source_active_task(db):
    repository = _Repository(conflicts=[SimpleNamespace(id="active-task")])
    service = _CapturingDispatchService(crawl_job_repository=repository)

    with pytest.raises(ActiveManualDetailCrawlConflict, match="active-task"):
        _dispatch(service, db)


def test_listing_dispatch_does_not_snapshot_or_query_detail_conflicts(db):
    repository = _Repository()
    service = _CapturingDispatchService(crawl_job_repository=repository)

    result = _dispatch(service, db, phase="listing")

    assert result.crawl_job.plan_request.listing_settings is not None
    assert result.crawl_job.plan_request.detail_settings is None
    assert repository.queries == []
