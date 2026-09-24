from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.ai.system_one import ChoiceAnswer, SystemOneResult, SystemOneUsage
from app.database import Base
import app.models  # noqa: F401
from app.models.crawl_job import CrawlJob
from app.models.crawl_job_listing import CrawlJobListing
from app.services.jev_crawl_quality_product import JevCrawlQualityProductService
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from scripts.bootstrap_db import bootstrap_database


def _session():
    database_url = os.getenv("JEV_CRAWL_QUALITY_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("disposable Jev crawl-quality PostgreSQL URL is not configured")
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "postgresql":
        raise RuntimeError("JEV_CRAWL_QUALITY_TEST_DATABASE_URL must use PostgreSQL")
    if not (make_url(database_url).database or "").endswith("_test"):
        raise RuntimeError("JEV_CRAWL_QUALITY_TEST_DATABASE_URL must end in _test")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    bootstrap_database(db_engine=engine, metadata=Base.metadata)
    db = sessionmaker(bind=engine, autoflush=False)()
    settings = JevRuntimeSettingsService(db).get_or_create()
    settings.enabled = True
    settings.api_key = "test-secret"
    settings.crawl_quality_enabled = True
    crawl_job = CrawlJob(
        id=uuid.uuid4(),
        source_site="offertoday",
        trigger_type="manual",
        status="completed",
        request_payload={"phase": "detail"},
    )
    db.add(crawl_job)
    db.flush()
    usable = CrawlJobListing(
        crawl_job_id=crawl_job.id,
        source_site="offertoday",
        source_job_id="quality-1",
        source_url="https://example.invalid/quality-1",
        listing_rank=1,
        listing_payload={"title": "Backend Engineer"},
        detail_payload={"description": "Search result template captured as a detail page."},
        detail_status="completed",
    )
    deterministic = CrawlJobListing(
        crawl_job_id=crawl_job.id,
        source_site="offertoday",
        source_job_id="quality-2",
        source_url="https://example.invalid/quality-2",
        listing_rank=2,
        listing_payload={"title": "Blocked"},
        detail_payload={"description": "Verify you are human"},
        detail_status="manual_action_required",
    )
    insufficient = CrawlJobListing(
        crawl_job_id=crawl_job.id,
        source_site="offertoday",
        source_job_id="quality-3",
        source_url="https://example.invalid/quality-3",
        listing_rank=3,
        listing_payload={},
        detail_payload=None,
        detail_status="failed",
    )
    db.add_all((usable, deterministic, insufficient))
    db.commit()
    return engine, db, crawl_job.id, usable.id, deterministic.id


def _dispose(engine, db):
    db.close()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


class _QualityEvaluator:
    def __init__(self):
        self.requests = []

    async def evaluate(self, request):
        self.requests.append(request)
        return SystemOneResult(
            status="answered",
            request_id="quality-request-1",
            model="jev-quality-resolved",
            provider="local-test",
            answers={
                "quality": ChoiceAnswer(
                    type="choice",
                    choice="quality_problem",
                    confidence=0.98,
                    probabilities={
                        "usable_job_detail": 0.01,
                        "quality_problem": 0.98,
                        "insufficient": 0.01,
                    },
                ),
                "problem_kind": ChoiceAnswer(
                    type="choice",
                    choice="listing_or_template",
                    confidence=0.97,
                    probabilities={"listing_or_template": 0.97, "other": 0.03},
                ),
            },
            usage=SystemOneUsage(input_tokens=60, output_tokens=8, cost=0.00002),
        )


class _UnavailableEvaluator:
    async def evaluate(self, request):
        return SystemOneResult(
            status="unavailable",
            request_id="quality-request-unavailable",
            model="jev-quality-resolved",
            provider="local-test",
            error_code="http_503",
            error_message="Provider unavailable",
        )


def test_preview_is_free_and_excludes_deterministic_and_insufficient_rows() -> None:
    engine, db, crawl_job_id, usable_id, _ = _session()
    try:
        preview = JevCrawlQualityProductService(db).preview(crawl_job_id, limit=10)
        assert preview.eligible_count == 1
        assert preview.selected_listing_ids == (usable_id,)
        assert preview.deterministic_excluded_count == 1
        assert preview.insufficient_excluded_count == 1
        assert db.query(CrawlJob).count() == 1
    finally:
        _dispose(engine, db)

@pytest.mark.asyncio
async def test_evaluation_persists_advisory_without_mutating_crawl_state() -> None:
    engine, db, crawl_job_id, usable_id, deterministic_id = _session()
    try:
        service = JevCrawlQualityProductService(db)
        evaluation = service.start(crawl_job_id, limit=10)
        evaluator = _QualityEvaluator()
        await service.execute(evaluation.id, evaluator=evaluator)
        db.commit()

        payload = service.latest(crawl_job_id)
        assert payload["status"] == "completed"
        assert payload["observations"][0]["quality"] == "quality_problem"
        assert payload["observations"][0]["problem_kind"] == "listing_or_template"
        assert payload["observations"][0]["request_id"] == "quality-request-1"
        assert len(evaluator.requests) == 1
        assert db.get(CrawlJob, crawl_job_id).status == "completed"
        assert db.get(CrawlJobListing, usable_id).detail_status == "completed"
        assert db.get(CrawlJobListing, deterministic_id).detail_status == "manual_action_required"
    finally:
        _dispose(engine, db)


@pytest.mark.asyncio
async def test_provider_unavailable_is_audited_without_mutating_crawl_state() -> None:
    engine, db, crawl_job_id, usable_id, deterministic_id = _session()
    try:
        service = JevCrawlQualityProductService(db)
        evaluation = service.start(crawl_job_id, limit=10)
        await service.execute(evaluation.id, evaluator=_UnavailableEvaluator())
        db.commit()

        payload = service.latest(crawl_job_id)
        assert payload["status"] == "completed_with_failures"
        assert payload["observations"] == [
            {
                "id": payload["observations"][0]["id"],
                "listing_id": str(usable_id),
                "source_identity": "offertoday:quality-1",
                "status": "unavailable",
                "quality": None,
                "problem_kind": None,
                "probabilities": {"quality": {}, "problem_kind": {}},
                "model": None,
                "request_id": None,
                "cost_usd": None,
                "error_code": "http_503",
            }
        ]
        assert db.get(CrawlJob, crawl_job_id).status == "completed"
        assert db.get(CrawlJobListing, usable_id).detail_status == "completed"
        assert (
            db.get(CrawlJobListing, deterministic_id).detail_status
            == "manual_action_required"
        )
    finally:
        _dispose(engine, db)
