from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.ai.system_one import ScoreAnswer, SystemOneResult, SystemOneUsage
from app.database import Base
import app.models  # noqa: F401
from app.models.company import Company
from app.models.job import Job
from app.models.jev import JevRun
from app.schemas.job_search import JobSearchScopeSchema
from app.search.deterministic_order import apply_deterministic_lexical_order
from app.search.lexical_query import build_lexical_query
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.services.jev_search_rerank import JevSearchRerankService
from scripts.bootstrap_db import bootstrap_database


def _session():
    database_url = os.getenv("JEV_SEARCH_RERANK_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("disposable Jev search-rerank PostgreSQL URL is not configured")
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "postgresql":
        raise RuntimeError("JEV_SEARCH_RERANK_TEST_DATABASE_URL must use PostgreSQL")
    if not (make_url(database_url).database or "").endswith("_test"):
        raise RuntimeError("JEV_SEARCH_RERANK_TEST_DATABASE_URL must end in _test")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    bootstrap_database(db_engine=engine, metadata=Base.metadata)
    db = sessionmaker(bind=engine, autoflush=False)()
    settings = JevRuntimeSettingsService(db).get_or_create()
    settings.enabled = True
    settings.api_key = "test-secret"
    settings.max_request_reservation_microdollars = 50_000
    settings.search_rerank_enabled = True
    settings.search_rerank_candidate_limit = 3
    company = Company(
        id=UUID("61000000-0000-0000-0000-000000000001"),
        company_id="search-company",
        source_site="jobsdb",
        source_company_id="search-company",
        name="Search Company",
    )
    db.add(company)
    created_at = datetime(2026, 9, 23, tzinfo=UTC)
    for index in range(1, 5):
        db.add(
            Job(
                id=UUID(f"62000000-0000-0000-0000-{index:012d}"),
                job_id=f"jobsdb:search-{index}",
                source_site="jobsdb",
                source_job_id=f"search-{index}",
                company_id=company.id,
                title=f"Python Engineer {index}",
                description=f"Python role candidate {index}",
                is_deleted=False,
                created_at=created_at,
                updated_at=created_at,
            )
        )
    db.commit()
    return engine, db


def _dispose(engine, db):
    db.close()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


class _ScoreEvaluator:
    def __init__(self, scores=(1.0, 3.0, 2.0)):
        self.scores = scores
        self.requests = []

    async def evaluate(self, request):
        self.requests.append(request)
        return SystemOneResult(
            status="answered",
            request_id="search-rerank-request-1",
            model="jev-search-resolved",
            provider="local-test",
            answers={
                name: ScoreAnswer(
                    type="score",
                    score=self.scores[index],
                    confidence=0.99,
                    legend={0: "irrelevant", 3: "highly relevant"},
                    probabilities={int(self.scores[index]): 1.0},
                )
                for index, name in enumerate(request.questions)
            },
            usage=SystemOneUsage(input_tokens=80, output_tokens=12, cost=0.00003),
        )


class _UnavailableEvaluator:
    def __init__(self):
        self.requests = []

    async def evaluate(self, request):
        self.requests.append(request)
        return SystemOneResult(
            status="unavailable",
            error_code="http_503",
            error_message="Provider unavailable",
        )


def test_preview_freezes_bounded_deterministic_prefix_without_a_run() -> None:
    engine, db = _session()
    try:
        service = JevSearchRerankService(db)
        evaluation = service.preview(
            scope=JobSearchScopeSchema(),
            retrieval_mode="lexical",
        )
        db.commit()

        payload = service.serialize(evaluation)
        assert payload["eligible_count"] == 4
        assert payload["selected_count"] == 3
        assert payload["baseline_job_ids"] == [
            "62000000-0000-0000-0000-000000000001",
            "62000000-0000-0000-0000-000000000002",
            "62000000-0000-0000-0000-000000000003",
            "62000000-0000-0000-0000-000000000004",
        ]
        assert db.query(JevRun).count() == 0
    finally:
        _dispose(engine, db)


@pytest.mark.asyncio
async def test_rerank_changes_only_frozen_prefix_and_pages_share_total_order() -> None:
    engine, db = _session()
    try:
        scope = JobSearchScopeSchema()
        service = JevSearchRerankService(db)
        evaluation = service.preview(scope=scope, retrieval_mode="lexical")
        evaluator = _ScoreEvaluator()
        await service.execute(evaluation.id, evaluator=evaluator)
        db.commit()

        payload = service.serialize(evaluation)
        assert payload["status"] == "completed"
        assert payload["ordered_job_ids"] == [
            "62000000-0000-0000-0000-000000000002",
            "62000000-0000-0000-0000-000000000003",
            "62000000-0000-0000-0000-000000000001",
            "62000000-0000-0000-0000-000000000004",
        ]
        assert payload["request_id"] == "search-rerank-request-1"
        assert len(evaluator.requests) == 1

        query = build_lexical_query(db, scope)
        ordered = service.apply_order(
            query,
            evaluation_id=evaluation.id,
            scope=scope,
            retrieval_mode="lexical",
        ).all()
        ordered_ids = [str(job.id) for job, _company in ordered]
        assert ordered_ids == payload["ordered_job_ids"]
        assert ordered_ids[:2] + ordered_ids[2:] == ordered_ids
        assert set(ordered_ids) == {
            "62000000-0000-0000-0000-000000000001",
            "62000000-0000-0000-0000-000000000002",
            "62000000-0000-0000-0000-000000000003",
            "62000000-0000-0000-0000-000000000004",
        }
    finally:
        _dispose(engine, db)


@pytest.mark.asyncio
async def test_provider_unavailable_preserves_exact_baseline_order() -> None:
    engine, db = _session()
    try:
        scope = JobSearchScopeSchema()
        service = JevSearchRerankService(db)
        evaluation = service.preview(scope=scope, retrieval_mode="lexical")
        evaluator = _UnavailableEvaluator()
        await service.execute(evaluation.id, evaluator=evaluator)
        db.commit()

        payload = service.serialize(evaluation)
        assert payload["status"] == "completed_with_failures"
        assert payload["error_code"] == "http_503"
        assert payload["ordered_job_ids"] == payload["baseline_job_ids"]
        assert len(evaluator.requests) == 1
    finally:
        _dispose(engine, db)


def test_scope_or_mode_drift_refuses_a_saved_order() -> None:
    engine, db = _session()
    try:
        service = JevSearchRerankService(db)
        scope = JobSearchScopeSchema()
        evaluation = service.preview(scope=scope, retrieval_mode="lexical")
        evaluation.status = "completed"
        db.flush()
        with pytest.raises(ValueError, match="does not match"):
            service.apply_order(
                apply_deterministic_lexical_order(build_lexical_query(db, scope)),
                evaluation_id=evaluation.id,
                scope=JobSearchScopeSchema(
                    layers=[
                        {
                            "client_id": "root",
                            "text_expression": "Python",
                            "structured_filters": {},
                        }
                    ]
                ),
                retrieval_mode="lexical",
            )
    finally:
        _dispose(engine, db)


def test_saved_order_excludes_new_members_and_rejects_missing_frozen_members() -> None:
    engine, db = _session()
    try:
        service = JevSearchRerankService(db)
        scope = JobSearchScopeSchema()
        evaluation = service.preview(scope=scope, retrieval_mode="lexical")
        evaluation.status = "completed"
        company = db.query(Company).one()
        db.add(
            Job(
                id=UUID("62000000-0000-0000-0000-000000000099"),
                job_id="jobsdb:search-99",
                source_site="jobsdb",
                source_job_id="search-99",
                company_id=company.id,
                title="Python Engineer 99",
                description="New after preview",
                is_deleted=False,
            )
        )
        db.flush()

        ordered = service.apply_order(
            build_lexical_query(db, scope),
            evaluation_id=evaluation.id,
            scope=scope,
            retrieval_mode="lexical",
        ).all()
        assert [str(job.id) for job, _company in ordered] == evaluation.baseline_job_ids
        facets = service.frozen_facets(
            evaluation.id,
            scope=scope,
            retrieval_mode="lexical",
        )
        assert next(item.count for item in facets.sources if item.id == "jobsdb") == 4

        frozen_job = db.get(Job, UUID(evaluation.baseline_job_ids[0]))
        frozen_job.is_deleted = True
        db.flush()
        with pytest.raises(ValueError, match="membership changed"):
            service.apply_order(
                build_lexical_query(db, scope),
                evaluation_id=evaluation.id,
                scope=scope,
                retrieval_mode="lexical",
            )
    finally:
        _dispose(engine, db)
