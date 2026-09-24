from __future__ import annotations

from datetime import datetime
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.ai.system_one import ChoiceAnswer, SystemOneResult, SystemOneUsage
from app.models.company import Company
from app.models.job import Job
from app.services.jev_duplicate_association import (
    DuplicateAssociationConflictError,
    JevDuplicateAssociationService,
)
from app.services.jev_runtime_settings_service import JevRuntimeSettingsService
from app.database import Base
import app.models  # noqa: F401
from scripts.bootstrap_db import bootstrap_database


def _session():
    database_url = os.getenv("JEV_DUPLICATE_TEST_DATABASE_URL", "").strip()
    if not database_url:
        pytest.skip("disposable Jev duplicate PostgreSQL URL is not configured")
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "postgresql":
        raise RuntimeError("JEV_DUPLICATE_TEST_DATABASE_URL must use PostgreSQL")
    if not (make_url(database_url).database or "").endswith("_test"):
        raise RuntimeError("JEV_DUPLICATE_TEST_DATABASE_URL must end in _test")
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    bootstrap_database(db_engine=engine, metadata=Base.metadata)
    db = sessionmaker(bind=engine, autoflush=False)()
    settings = JevRuntimeSettingsService(db)
    settings.get_or_create()
    settings.update(
        {
            "enabled": True,
            "api_key": "test-secret",
        }
    )
    company = Company(
        id=uuid.uuid4(),
        company_id="company-1",
        source_site="jobsdb",
        source_company_id="company-1",
        name="Example Limited",
    )
    db.add(company)
    left = Job(
        id=uuid.uuid4(),
        job_id="jobsdb:101",
        source_site="jobsdb",
        source_job_id="101",
        company_id=company.id,
        title="Backend Engineer",
        description="<p>Build Python APIs for the payments team.</p>",
        location="Hong Kong",
        posted_date=datetime(2026, 9, 20),
        is_deleted=False,
    )
    right = Job(
        id=uuid.uuid4(),
        job_id="ctgoodjobs:202",
        source_site="ctgoodjobs",
        source_job_id="202",
        company_id=company.id,
        title="Backend Engineer",
        description="Build Python APIs for the payments team.",
        location="Hong Kong",
        posted_date=datetime(2026, 9, 21),
        is_deleted=False,
    )
    db.add_all((left, right))
    db.commit()
    return engine, db, left.id, right.id


def _dispose(db, engine) -> None:
    db.close()
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()


class _SameVacancyEvaluator:
    def __init__(self):
        self.requests = []

    async def evaluate(self, request):
        self.requests.append(request)
        return SystemOneResult(
            status="answered",
            request_id="jev-request-1",
            model="jev-latest",
            provider="openrouter",
            answers={
                "decision": ChoiceAnswer(
                    type="choice",
                    choice="same_vacancy",
                    confidence=0.97,
                    probabilities={
                        "same_vacancy": 0.97,
                        "different_vacancy": 0.02,
                        "insufficient": 0.01,
                    },
                )
            },
            usage=SystemOneUsage(input_tokens=100, output_tokens=8, cost=0.001),
            latency_ms=15,
        )


@pytest.mark.asyncio
async def test_product_evaluation_creates_proposal_without_mutating_source_jobs() -> None:
    engine, db, left_id, right_id = _session()
    try:
        service = JevDuplicateAssociationService(db)
        plan = service.start_for_job(left_id, candidate_limit=1, corpus_limit=10)
        evaluator = _SameVacancyEvaluator()
        assert plan.candidate_count == 1

        await service.execute(plan.run_id, evaluator=evaluator)
        db.commit()

        associations = service.list_for_job(left_id)
        assert len(associations) == 1
        assert associations[0]["status"] == "proposed"
        assert associations[0]["confidence"] == 0.97
        assert associations[0]["other_job"]["id"] == str(right_id)
        assert associations[0]["receipt"] == {
            "model": "jev-latest",
            "request_id": "jev-request-1",
            "cost_usd": 0.001,
        }
        assert len(evaluator.requests) == 1
        assert evaluator.requests[0].questions["decision"].criteria.keys() == {
            "same_vacancy",
            "different_vacancy",
            "insufficient",
        }
        assert db.get(Job, left_id).is_deleted is False
        assert db.get(Job, right_id).is_deleted is False

        replay = service.start_for_job(left_id, candidate_limit=1, corpus_limit=10)
        assert replay.run_id is None
        assert replay.skipped_current_count == 1
    finally:
        _dispose(db, engine)


@pytest.mark.asyncio
async def test_reverse_job_read_returns_same_source_preserving_association() -> None:
    engine, db, left_id, right_id = _session()
    try:
        service = JevDuplicateAssociationService(db)
        plan = service.start_for_job(right_id, candidate_limit=1, corpus_limit=10)
        await service.execute(plan.run_id, evaluator=_SameVacancyEvaluator())
        db.commit()

        result = service.list_for_job(right_id)
        assert result[0]["other_job"]["id"] == str(left_id)
        assert result[0]["other_job"]["source_site"] == "jobsdb"
    finally:
        _dispose(db, engine)


@pytest.mark.asyncio
async def test_operator_review_is_idempotent_and_never_mutates_source_jobs() -> None:
    engine, db, left_id, right_id = _session()
    try:
        service = JevDuplicateAssociationService(db)
        plan = service.start_for_job(left_id, candidate_limit=1, corpus_limit=10)
        await service.execute(plan.run_id, evaluator=_SameVacancyEvaluator())
        proposal = service.list_for_job(left_id)[0]

        first = service.review(
            proposal["id"],
            subject_job_id=left_id,
            action="confirm",
            idempotency_key="duplicate-review-1",
        )
        replay = service.review(
            proposal["id"],
            subject_job_id=left_id,
            action="confirm",
            idempotency_key="duplicate-review-1",
        )
        assert first == replay
        assert replay["status"] == "confirmed"
        assert db.get(Job, left_id).is_deleted is False
        assert db.get(Job, right_id).is_deleted is False

        with pytest.raises(DuplicateAssociationConflictError):
            service.review(
                proposal["id"],
                subject_job_id=left_id,
                action="reject",
                idempotency_key="duplicate-review-1",
            )
    finally:
        _dispose(db, engine)


@pytest.mark.asyncio
async def test_changed_job_evidence_hides_the_old_association_claim() -> None:
    engine, db, left_id, _right_id = _session()
    try:
        service = JevDuplicateAssociationService(db)
        plan = service.start_for_job(left_id, candidate_limit=1, corpus_limit=10)
        await service.execute(plan.run_id, evaluator=_SameVacancyEvaluator())
        assert len(service.list_for_job(left_id)) == 1

        db.get(Job, left_id).description = "A materially different security role."
        db.flush()

        assert service.list_for_job(left_id) == []
        next_plan = service.start_for_job(left_id, candidate_limit=1, corpus_limit=10)
        assert next_plan.run_id is not None
        assert next_plan.candidate_count == 1
    finally:
        _dispose(db, engine)
